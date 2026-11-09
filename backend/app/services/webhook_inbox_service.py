"""
NEXUS Phase 1J.2.2 — Durable Provider-Neutral Webhook Inbox Service.

Provides:
1. Durable database-backed webhook deduplication across worker restarts and multiple instances.
2. Atomic event claiming with row-level locking (SELECT FOR UPDATE) to eliminate race conditions.
3. Stale worker recovery for interrupted event processing.
4. Tenant-scoped access and auditability.
5. Support for both Stripe and Shopify webhook event models.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connector import ConnectorWebhookInbox
from app.models.tenant import Business

logger = logging.getLogger(__name__)


class WebhookInboxService:
    """
    Durable, provider-neutral webhook event deduplication and processing service.
    """

    @classmethod
    def record_incoming_event(
        cls,
        session: Session,
        business_id: str,
        provider: str,
        provider_account_id: str,
        event_id: str,
        event_type: str,
        payload_bytes: bytes,
        event_created_at: datetime | None = None,
        signature_verified: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ConnectorWebhookInbox, bool]:
        """
        Record an incoming webhook event into the durable database inbox.
        Returns (inbox_item, is_new).
        If (provider, provider_account_id, event_id) already exists, returns (existing_item, False).
        """
        # Multi-tenant validation: business must exist
        biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        if not biz:
            raise ValueError(f"Tenant business '{business_id}' does not exist.")

        # Check existing record
        existing = session.execute(
            select(ConnectorWebhookInbox).where(
                ConnectorWebhookInbox.provider == provider,
                ConnectorWebhookInbox.provider_account_id == provider_account_id,
                ConnectorWebhookInbox.event_id == event_id,
            )
        ).scalar_one_or_none()

        # Compute SHA-256 payload digest
        digest = hashlib.sha256(payload_bytes).hexdigest()

        if existing:
            # Enforce tenant isolation: existing event must belong to the same business
            if existing.business_id != business_id:
                raise PermissionError(
                    f"Security Violation: Webhook event '{event_id}' is registered to tenant '{existing.business_id}', "
                    f"cannot be accessed or updated by tenant '{business_id}'."
                )

            # Payload changes under an existing event ID are quarantined
            if existing.payload_digest != digest:
                existing.status = "QUARANTINED"
                existing.last_error = (
                    f"QUARANTINED: Payload digest mismatch for event '{event_id}'. "
                    f"Existing digest: {existing.payload_digest}, incoming digest: {digest}."
                )
                meta = dict(existing.metadata_json or {})
                meta["quarantine_reason"] = "PAYLOAD_DIGEST_MISMATCH"
                meta["quarantined_at"] = datetime.now(UTC).isoformat()
                meta["conflicting_digest"] = digest
                existing.metadata_json = meta
                session.flush()
                return existing, False

            return existing, False

        inbox_item = ConnectorWebhookInbox(
            business_id=business_id,
            provider=provider,
            provider_account_id=provider_account_id,
            event_id=event_id,
            event_type=event_type,
            event_created_at=event_created_at,
            received_at=datetime.now(UTC),
            signature_verified=signature_verified,
            status="PENDING",
            retry_count=0,
            payload_digest=digest,
            metadata_json=metadata or {},
        )
        session.add(inbox_item)
        session.flush()
        return inbox_item, True

    @classmethod
    def claim_event_for_processing(
        cls,
        session: Session,
        inbox_id: str,
        worker_id: str = "worker_default",
        stale_timeout_minutes: int = 5,
        skip_locked: bool = False,
    ) -> ConnectorWebhookInbox | None:
        """
        Atomically claim a webhook event for processing using row-level locking.
        Supports automatic recovery if a worker crashed and left the event in CLAIMED status.
        Returns the claimed item, or None if already completed or actively locked by another worker.
        """
        stmt = (
            select(ConnectorWebhookInbox)
            .where(ConnectorWebhookInbox.id == inbox_id)
            .with_for_update(skip_locked=skip_locked)
        )
        item = session.execute(stmt).scalar_one_or_none()
        if not item:
            return None

        now = datetime.now(UTC)

        # Event already completed or quarantined
        if item.status in ("PROCESSED", "QUARANTINED"):
            return None

        # Check if can be claimed
        can_claim = False
        if item.status == "PENDING" or item.status == "FAILED":
            can_claim = True
        elif item.status == "CLAIMED":
            # Check stale worker timeout with active heartbeat consideration
            last_active = item.claimed_at
            if item.metadata_json and "last_heartbeat_at" in item.metadata_json:
                try:
                    hb_dt = datetime.fromisoformat(item.metadata_json["last_heartbeat_at"])
                    if hb_dt.tzinfo is None:
                        hb_dt = hb_dt.replace(tzinfo=UTC)
                    last_active = hb_dt
                except (ValueError, TypeError):
                    pass

            if last_active:
                c_at = last_active if last_active.tzinfo else last_active.replace(tzinfo=UTC)
                if (now - c_at) > timedelta(minutes=stale_timeout_minutes):
                    logger.warning(
                        f"Recovering stale webhook event '{item.event_id}' claimed by '{item.claimed_by}' "
                        f"with last activity at {c_at}."
                    )
                    can_claim = True

        if not can_claim:
            return None

        item.status = "CLAIMED"
        item.claimed_by = worker_id
        item.claimed_at = now
        item.retry_count += 1
        session.flush()
        return item

    @classmethod
    def claim_pending_events(
        cls,
        session: Session,
        worker_id: str = "worker_default",
        limit: int = 10,
        provider: str | None = None,
        skip_locked: bool = True,
    ) -> list[ConnectorWebhookInbox]:
        """
        Atomically claim a batch of pending webhook events using row-level SKIP LOCKED.
        Prevents worker lock contention in high-throughput multi-worker environments.
        """
        query = select(ConnectorWebhookInbox).where(ConnectorWebhookInbox.status == "PENDING")
        if provider:
            query = query.where(ConnectorWebhookInbox.provider == provider)
        query = query.order_by(ConnectorWebhookInbox.created_at.asc()).limit(limit).with_for_update(skip_locked=skip_locked)
        items = list(session.execute(query).scalars().all())
        now = datetime.now(UTC)
        for item in items:
            item.status = "CLAIMED"
            item.claimed_by = worker_id
            item.claimed_at = now
            item.retry_count += 1
        session.flush()
        return items

    @classmethod
    def record_heartbeat(
        cls,
        session: Session,
        inbox_id: str,
        worker_id: str,
    ) -> ConnectorWebhookInbox:
        """
        Record an active worker heartbeat to renew lock freshness and prevent premature recovery.
        """
        stmt = (
            select(ConnectorWebhookInbox)
            .where(ConnectorWebhookInbox.id == inbox_id)
            .with_for_update()
        )
        item = session.execute(stmt).scalar_one_or_none()
        if not item:
            raise ValueError(f"Webhook inbox record '{inbox_id}' not found.")
        if item.status != "CLAIMED":
            raise ValueError(f"Cannot heartbeat event '{inbox_id}' with status '{item.status}'.")
        if item.claimed_by != worker_id:
            raise PermissionError(
                f"Worker '{worker_id}' cannot heartbeat event '{inbox_id}' locked by '{item.claimed_by}'."
            )

        now = datetime.now(UTC)
        item.claimed_at = now
        meta = dict(item.metadata_json or {})
        meta["last_heartbeat_at"] = now.isoformat()
        item.metadata_json = meta
        session.flush()
        return item

    @classmethod
    def complete_event_processing(
        cls,
        session: Session,
        inbox_id: str,
        metadata_updates: dict[str, Any] | None = None,
    ) -> ConnectorWebhookInbox:
        """
        Mark a claimed webhook event as successfully PROCESSED.
        """
        item = session.execute(
            select(ConnectorWebhookInbox)
            .where(ConnectorWebhookInbox.id == inbox_id)
            .with_for_update()
        ).scalar_one_or_none()

        if not item:
            raise ValueError(f"Webhook inbox record '{inbox_id}' not found.")

        item.status = "PROCESSED"
        item.processed_at = datetime.now(UTC)
        item.last_error = None

        if metadata_updates:
            meta = dict(item.metadata_json or {})
            meta.update(metadata_updates)
            item.metadata_json = meta

        session.flush()
        return item

    @classmethod
    def fail_event_processing(
        cls,
        session: Session,
        inbox_id: str,
        error_message: str,
    ) -> ConnectorWebhookInbox:
        """
        Mark a claimed webhook event as FAILED with error telemetry.
        """
        item = session.execute(
            select(ConnectorWebhookInbox)
            .where(ConnectorWebhookInbox.id == inbox_id)
            .with_for_update()
        ).scalar_one_or_none()

        if not item:
            raise ValueError(f"Webhook inbox record '{inbox_id}' not found.")

        item.status = "FAILED"
        item.last_error = error_message
        session.flush()
        return item

    @classmethod
    def process_inbound_webhook(
        cls,
        session: Session,
        adapter: Any,
        headers: dict[str, str],
        body_bytes: bytes,
        worker_id: str = "worker_default",
        handler: Callable[[Session, dict[str, Any], ConnectorWebhookInbox], Any] | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        blocking: bool = True,
    ) -> dict[str, Any]:
        """
        End-to-end durable webhook processing pipeline:
        1. Verify signature via adapter.
        2. Parse event ID and topic.
        3. Acquire ingestion writer coordination lock if period bounds are specified.
        4. Record into durable inbox (handling duplicates idempotently and quarantining payload mismatches).
        5. Claim event atomically (row-level lock).
        6. Execute transactional handler (if provided).
        7. Mark complete or fail with isolated transaction boundary.
        """
        # 1. Verify signature
        if not adapter.verify_event_signature(headers, body_bytes):
            from stripe import SignatureVerificationError
            raise SignatureVerificationError(
                "Invalid webhook signature or expired timestamp.",
                sig_header="stripe-or-shopify-signature",
            )

        # 2. Parse payload and provider metadata
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Malformed webhook JSON payload: {e}") from e

        provider = adapter.get_metadata().provider
        provider_account_id = adapter.get_metadata().provider_account_id
        business_id = adapter.business_id

        # Determine event_id, event_type, and event_dt based on provider conventions
        if provider == "stripe":
            event_id = payload.get("id")
            event_type = payload.get("type", "unknown")
            created_ts = payload.get("created")
            event_dt = datetime.fromtimestamp(created_ts, tz=UTC) if created_ts else datetime.now(UTC)
        elif provider == "shopify":
            # Header lookup (case-insensitive)
            h_lower = {k.lower(): v for k, v in headers.items()}
            event_id = (
                h_lower.get("x-shopify-webhook-id")
                or str(payload.get("id"))
                or str(payload.get("admin_graphql_api_id"))
            )
            event_type = h_lower.get("x-shopify-topic") or "orders/create"
            event_dt = datetime.now(UTC)
        else:
            event_id = payload.get("id") or str(uuid4())
            event_type = payload.get("event_type", "unknown")
            event_dt = datetime.now(UTC)

        # Enforce ingestion writer coordination protocol (explicit or derived period bounds)
        from app.services.ingestion_writer_coordinator import IngestionWriterCoordinator

        if period_start is not None and period_end is not None:
            p_start, p_end = period_start, period_end
        else:
            # Auto-derive monthly accounting period bounds from webhook event timestamp
            safe_dt = event_dt if event_dt.tzinfo is not None else event_dt.replace(tzinfo=UTC)
            p_start = safe_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            p_end = (p_start.replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        IngestionWriterCoordinator.acquire_ingestion_lock(
            session=session,
            business_id=business_id,
            period_start=p_start,
            period_end=p_end,
            blocking=blocking,
        )

        if not event_id:
            raise ValueError(f"Missing event identifier in {provider} webhook.")

        # 3. Record into durable inbox
        inbox_item, is_new = cls.record_incoming_event(
            session=session,
            business_id=business_id,
            provider=provider,
            provider_account_id=provider_account_id,
            event_id=str(event_id),
            event_type=event_type,
            payload_bytes=body_bytes,
            event_created_at=event_dt,
            signature_verified=True,
            metadata={"headers": {k: v for k, v in headers.items() if "secret" not in k.lower()}},
        )

        if inbox_item.status == "QUARANTINED":
            return {
                "status": "quarantined",
                "event_id": str(event_id),
                "inbox_id": inbox_item.id,
                "message": inbox_item.last_error or "Webhook event quarantined due to payload digest mismatch.",
            }

        if not is_new:
            if inbox_item.status == "PROCESSED":
                return {
                    "status": "duplicate_ignored",
                    "event_id": str(event_id),
                    "inbox_id": inbox_item.id,
                    "message": f"Webhook event '{event_id}' has already been processed.",
                }
            elif inbox_item.status == "CLAIMED":
                return {
                    "status": "duplicate_in_progress",
                    "event_id": str(event_id),
                    "inbox_id": inbox_item.id,
                    "message": f"Webhook event '{event_id}' is currently being processed by another worker.",
                }

        # 4. Claim event atomically
        claimed = cls.claim_event_for_processing(session, inbox_item.id, worker_id=worker_id)
        if not claimed:
            return {
                "status": "duplicate_ignored",
                "event_id": str(event_id),
                "inbox_id": inbox_item.id,
                "message": f"Webhook event '{event_id}' could not be claimed (already processed or active).",
            }

        # 5. Execute transactional handler if provided
        try:
            if handler is not None:
                handler(session, payload, claimed)
            cls.complete_event_processing(session, inbox_item.id, metadata_updates={"claimed_by": worker_id})
        except Exception as exc:
            cls.fail_event_processing(session, inbox_item.id, error_message=str(exc))
            raise

        return {
            "status": "processed",
            "event_id": str(event_id),
            "inbox_id": inbox_item.id,
            "event_type": event_type,
            "processed_at": datetime.now(UTC).isoformat(),
        }
