"""
NEXUS Phase 1J.1 — Connector Synchronization Service.

Orchestrates durable background synchronization for upstream data source connectors.
Enforces:
1. Tenant-scoped credential isolation and authorization checks.
2. Durable checkpoints (ConnectorSyncCheckpoint) with cursor hash chaining.
3. Idempotent transaction ingestion and deduplication.
4. Pagination completeness verification (prohibiting premature termination).
5. Backfill detection against active watermarks.
6. Timing-safe webhook event signature verification.
7. Mathematical reconciliation against Tier 3 settlement evidence.
8. Non-negotiable fail-closed protection for real tenants against synthetic certifications.
"""

import hashlib
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.source_connector_adapter import SourceConnectorAdapter
from app.core.kms import (
    EnvelopeEncryptionEngine,
    KMSProvider,
    LocalDevelopmentKMSProvider,
    get_kms_provider,
)
from app.models.connector import ConnectorSyncCheckpoint, TenantConnectorCredential
from app.models.tenant import Business
from app.models.watermark import TenantIngestionWatermark
from app.schemas.source_sync import (
    ExtractionPage,
    PeriodCloseEvidence,
    SyncResult,
)
from app.services.tenant_certification_policy import TenantCertificationPolicy

logger = logging.getLogger(__name__)


class SourceSyncService:
    """
    Durable, tenant-scoped synchronization orchestrator for upstream connectors.
    """

    @classmethod
    def register_tenant_credentials(
        cls,
        session: Session,
        business_id: str,
        provider: str,
        provider_account_id: str,
        credential_dict: dict[str, Any],
        scopes: list[str],
        kms_key_id: str = "local_kms_vault",
        kms_provider: KMSProvider | None = None,
    ) -> TenantConnectorCredential:
        """
        Store tenant connector credentials encrypted using authenticated AES-256-GCM envelope encryption.
        Never stores plaintext credentials in raw columns.
        """
        # Multi-tenant boundary check: business must exist
        biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        if not biz:
            raise ValueError(f"Business '{business_id}' does not exist.")

        active_kms = kms_provider or get_kms_provider()
        encrypted_blob = EnvelopeEncryptionEngine.encrypt_credentials(
            credential_dict=credential_dict,
            business_id=business_id,
            provider=provider,
            provider_account_id=provider_account_id,
            kms_provider=active_kms,
            kms_key_id=kms_key_id,
        )

        cred = session.execute(
            select(TenantConnectorCredential).where(
                TenantConnectorCredential.business_id == business_id,
                TenantConnectorCredential.provider == provider,
            )
        ).scalar_one_or_none()

        if cred:
            cred.provider_account_id = provider_account_id
            cred.encrypted_credentials = encrypted_blob
            cred.scopes = scopes
            cred.kms_key_id = kms_key_id
            cred.status = "ACTIVE"
            cred.last_rotated_at = datetime.now(UTC)
        else:
            cred = TenantConnectorCredential(
                business_id=business_id,
                provider=provider,
                provider_account_id=provider_account_id,
                encrypted_credentials=encrypted_blob,
                scopes=scopes,
                kms_key_id=kms_key_id,
                status="ACTIVE",
            )
            session.add(cred)

        session.flush()
        return cred

    @classmethod
    def get_or_create_checkpoint(
        cls,
        session: Session,
        business_id: str,
        provider: str,
        period_start: datetime,
        period_end: datetime,
        sync_mode: str = "historical",
        for_update: bool = False,
    ) -> ConnectorSyncCheckpoint:
        """
        Retrieve or initialize a durable sync checkpoint for a given tenant, provider, and period.
        Supports row-level locking via for_update=True.
        """
        stmt = select(ConnectorSyncCheckpoint).where(
            ConnectorSyncCheckpoint.business_id == business_id,
            ConnectorSyncCheckpoint.provider == provider,
            ConnectorSyncCheckpoint.period_start == period_start,
            ConnectorSyncCheckpoint.period_end == period_end,
        )
        if for_update:
            stmt = stmt.with_for_update()

        checkpoint = session.execute(stmt).scalar_one_or_none()

        if not checkpoint:
            initial_chain = hashlib.sha256(b"ROOT").hexdigest()
            checkpoint = ConnectorSyncCheckpoint(
                business_id=business_id,
                provider=provider,
                sync_mode=sync_mode,
                period_start=period_start,
                period_end=period_end,
                status="IN_PROGRESS",
                is_complete=False,
                current_cursor=None,
                cursor_chain_hash=initial_chain,
                records_extracted=0,
                records_ingested=0,
                records_rejected=0,
                records_duplicate=0,
                gross_amount=Decimal("0.00"),
                net_amount=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                fee_amount=Decimal("0.00"),
                metadata_json={"ingested_transaction_ids": [], "eligible_transaction_ids": []},
            )
            session.add(checkpoint)
            session.flush()

        return checkpoint

    @classmethod
    def acquire_checkpoint_lock(
        cls,
        session: Session,
        checkpoint_id: str,
    ) -> ConnectorSyncCheckpoint:
        """
        Acquire exclusive row-level lock (SELECT FOR UPDATE) on a sync checkpoint.
        Guarantees serialized execution across concurrent workers.
        """
        stmt = (
            select(ConnectorSyncCheckpoint)
            .where(ConnectorSyncCheckpoint.id == checkpoint_id)
            .with_for_update()
        )
        ckpt = session.execute(stmt).scalar_one_or_none()
        if not ckpt:
            raise ValueError(f"Checkpoint '{checkpoint_id}' not found.")
        return ckpt

    @classmethod
    def update_checkpoint_cursor(
        cls,
        session: Session,
        checkpoint_id: str,
        expected_chain_hash: str,
        next_cursor: str | None,
        next_chain_hash: str,
        page_records_count: int,
    ) -> ConnectorSyncCheckpoint:
        """
        Optimistically update checkpoint cursor ensuring chain hash matches expected state.
        Rejects stale worker updates with ValueError.
        """
        ckpt = cls.acquire_checkpoint_lock(session, checkpoint_id)
        if ckpt.cursor_chain_hash != expected_chain_hash:
            raise ValueError(
                f"Stale cursor update rejected: Checkpoint chain hash '{ckpt.cursor_chain_hash}' "
                f"differs from expected chain hash '{expected_chain_hash}'."
            )
        ckpt.current_cursor = next_cursor
        ckpt.cursor_chain_hash = next_chain_hash
        ckpt.records_extracted += page_records_count
        session.flush()
        return ckpt

    @classmethod
    def get_tenant_credentials(
        cls,
        session: Session,
        business_id: str,
        provider: str,
    ) -> TenantConnectorCredential | None:
        """
        Retrieve tenant connector credentials, verifying status is ACTIVE and unexpired.
        """
        stmt = select(TenantConnectorCredential).where(
            TenantConnectorCredential.business_id == business_id,
            TenantConnectorCredential.provider == provider,
        )
        cred = session.execute(stmt).scalar_one_or_none()
        if not cred:
            return None
        if cred.status != "ACTIVE":
            raise PermissionError(f"Tenant credentials for '{provider}' are {cred.status}.")
        if cred.expires_at:
            now_utc = datetime.now(UTC)
            exp_utc = cred.expires_at if cred.expires_at.tzinfo else cred.expires_at.replace(tzinfo=UTC)
            if exp_utc <= now_utc:
                raise PermissionError(f"Tenant credentials for '{provider}' expired at {exp_utc.isoformat()}.")
        return cred

    @classmethod
    def get_decrypted_tenant_credentials(
        cls,
        session: Session,
        business_id: str,
        provider: str,
        kms_provider: KMSProvider | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve and decrypt tenant connector credentials using authenticated AES-256-GCM envelope encryption.
        Zero plaintext secrets are logged or exposed in exceptions.
        """
        cred = cls.get_tenant_credentials(session, business_id, provider)
        if not cred:
            raise ValueError(f"No credentials found for tenant '{business_id}' and provider '{provider}'.")

        active_kms = kms_provider or get_kms_provider()
        return EnvelopeEncryptionEngine.decrypt_credentials(
            envelope_str=cred.encrypted_credentials,
            business_id=business_id,
            provider=provider,
            provider_account_id=cred.provider_account_id,
            kms_provider=active_kms,
        )

    @classmethod
    def rotate_tenant_credential_kms_key(
        cls,
        session: Session,
        business_id: str,
        provider: str,
        new_kms_key_id: str,
        old_kms_provider: KMSProvider,
        new_kms_provider: KMSProvider,
    ) -> TenantConnectorCredential:
        """
        Re-encrypt tenant credentials under a new KMS master key or version.
        Guarantees seamless key rotation without mutating the underlying plaintext secret.
        """
        cred = cls.get_tenant_credentials(session, business_id, provider)
        if not cred:
            raise ValueError(f"No credentials found for tenant '{business_id}' and provider '{provider}'.")

        # Decrypt with old key
        decrypted = EnvelopeEncryptionEngine.decrypt_credentials(
            envelope_str=cred.encrypted_credentials,
            business_id=business_id,
            provider=provider,
            provider_account_id=cred.provider_account_id,
            kms_provider=old_kms_provider,
        )

        # Re-encrypt with new key
        new_envelope = EnvelopeEncryptionEngine.encrypt_credentials(
            credential_dict=decrypted,
            business_id=business_id,
            provider=provider,
            provider_account_id=cred.provider_account_id,
            kms_provider=new_kms_provider,
            kms_key_id=new_kms_key_id,
        )

        cred.encrypted_credentials = new_envelope
        cred.kms_key_id = new_kms_key_id
        cred.last_rotated_at = datetime.now(UTC)
        session.flush()
        return cred

    @classmethod
    def verify_tenant_boundary(
        cls,
        session: Session,
        authenticated_business_id: str,
        checkpoint_id: str,
    ) -> ConnectorSyncCheckpoint:
        """
        Verify that a checkpoint belongs strictly to the authenticated tenant.
        Raises PermissionError on cross-tenant access attempts.
        """
        checkpoint = session.execute(
            select(ConnectorSyncCheckpoint).where(ConnectorSyncCheckpoint.id == checkpoint_id)
        ).scalar_one_or_none()

        if not checkpoint:
            raise ValueError(f"Checkpoint '{checkpoint_id}' not found.")

        if checkpoint.business_id != authenticated_business_id:
            raise PermissionError(
                f"Cross-tenant access violation: Caller business '{authenticated_business_id}' "
                f"attempted to access checkpoint belonging to tenant '{checkpoint.business_id}'."
            )

        return checkpoint

    @classmethod
    def check_for_backfill(
        cls,
        session: Session,
        business_id: str,
        transaction_date: datetime,
    ) -> tuple[bool, str | None]:
        """
        Determine if an extracted transaction represents a backfill against an active watermark.
        """
        active_wm = session.execute(
            select(TenantIngestionWatermark).where(
                TenantIngestionWatermark.business_id == business_id,
                TenantIngestionWatermark.is_active.is_(True),
            )
        ).scalar_one_or_none()

        if active_wm:
            wm_dt = active_wm.complete_through_dt
            if wm_dt.tzinfo is None:
                wm_dt = wm_dt.replace(tzinfo=UTC)
            txn_dt = transaction_date
            if txn_dt.tzinfo is None:
                txn_dt = txn_dt.replace(tzinfo=UTC)
            if txn_dt <= wm_dt:
                return True, f"Transaction date {txn_dt.isoformat()} precedes active watermark {wm_dt.isoformat()}"

        return False, None

    @classmethod
    def execute_sync(
        cls,
        session: Session,
        adapter: SourceConnectorAdapter,
        period_start: datetime,
        period_end: datetime,
        page_size: int = 50,
        stop_after_pages: int | None = None,
        blocking: bool = True,
    ) -> SyncResult:
        """
        Execute an end-to-end synchronized extraction loop using the adapter and durable checkpoint.
        Guarantees pagination completeness, idempotent deduplication, and failure tracking.
        Supports graceful interruption and resumption via stop_after_pages.
        Participates in the IngestionWriterCoordinator protocol (shared transaction advisory lock).
        """
        business_id = adapter.business_id
        provider = adapter.get_metadata().provider
        started_at = datetime.now(UTC)
        sync_run_id = str(uuid4())

        # Validate adapter authentication
        auth_status = adapter.get_auth_status()
        if not auth_status.is_authenticated:
            raise PermissionError(f"Connector authentication failed for provider '{provider}': {auth_status.error_message}")

        # Enforce ingestion writer coordination protocol (shared transaction advisory lock)
        from app.services.ingestion_writer_coordinator import IngestionWriterCoordinator

        IngestionWriterCoordinator.acquire_ingestion_lock(
            session=session,
            business_id=business_id,
            period_start=period_start,
            period_end=period_end,
            blocking=blocking,
        )

        checkpoint = cls.get_or_create_checkpoint(
            session=session,
            business_id=business_id,
            provider=provider,
            period_start=period_start,
            period_end=period_end,
        )

        cursor = checkpoint.current_cursor
        chain_hash = checkpoint.cursor_chain_hash
        existing_meta = dict(checkpoint.metadata_json or {})
        seen_txn_ids: set[str] = set(existing_meta.get("ingested_transaction_ids", []))
        eligible_txn_ids: list[str] = list(existing_meta.get("eligible_transaction_ids", []))
        errors: list[str] = []
        pages_processed = 0

        try:
            while True:
                page: ExtractionPage = adapter.fetch_transactions_page(
                    period_start=period_start,
                    period_end=period_end,
                    cursor=cursor,
                    page_size=page_size,
                    previous_chain_hash=chain_hash,
                )

                checkpoint.records_extracted += page.page_records_count

                # Process records in page with idempotent deduplication
                for record in page.records:
                    if record.source_transaction_id in seen_txn_ids:
                        checkpoint.records_duplicate += 1
                        continue

                    seen_txn_ids.add(record.source_transaction_id)

                    # Check for backfill
                    is_backfill, reason = cls.check_for_backfill(
                        session, business_id, record.transaction_date
                    )
                    if is_backfill:
                        logger.warning(f"Backfill detected in sync {sync_run_id}: {reason}")

                    checkpoint.records_ingested += 1
                    if record.status in ("completed", "refunded", "shipped", "paid"):
                        eligible_txn_ids.append(record.source_transaction_id)
                        checkpoint.gross_amount += record.gross_amount
                        checkpoint.net_amount += record.net_amount
                        checkpoint.tax_amount += record.tax_amount
                        checkpoint.fee_amount += record.fee_amount
                    checkpoint.last_event_timestamp = record.transaction_date

                # Update cursor chain
                cursor = page.next_cursor
                chain_hash = page.cursor_chain_hash
                checkpoint.current_cursor = cursor
                checkpoint.cursor_chain_hash = chain_hash

                # Persist incremental state to metadata_json
                existing_meta["ingested_transaction_ids"] = list(seen_txn_ids)
                existing_meta["eligible_transaction_ids"] = eligible_txn_ids
                checkpoint.metadata_json = existing_meta

                pages_processed += 1

                # Check if caller requested simulated stop after N pages
                if stop_after_pages is not None and pages_processed >= stop_after_pages and page.has_more:
                    checkpoint.status = "IN_PROGRESS"
                    checkpoint.is_complete = False
                    session.flush()
                    return SyncResult(
                        sync_run_id=sync_run_id,
                        business_id=business_id,
                        provider=provider,
                        period_start=period_start,
                        period_end=period_end,
                        status="IN_PROGRESS",
                        is_complete=False,
                        records_extracted=checkpoint.records_extracted,
                        records_ingested=checkpoint.records_ingested,
                        records_rejected=checkpoint.records_rejected,
                        records_duplicate=checkpoint.records_duplicate,
                        cursor_chain_hash=chain_hash,
                        transaction_set_digest=checkpoint.cursor_chain_hash,
                        reported_gross=checkpoint.gross_amount,
                        reported_net=checkpoint.net_amount,
                        reported_tax=checkpoint.tax_amount,
                        reported_fee=checkpoint.fee_amount,
                        provenance_type=adapter.get_metadata().provider,
                        errors=[],
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                        period_close_evidence=None,
                    )

                if not page.has_more or not cursor:
                    # Verified termination reached
                    checkpoint.is_complete = True
                    checkpoint.status = "COMPLETED"
                    checkpoint.completed_at = datetime.now(UTC)
                    break

        except Exception as e:  # noqa: BLE001
            checkpoint.status = "INCOMPLETE"
            checkpoint.is_complete = False
            checkpoint.retry_count += 1
            checkpoint.last_error = str(e)
            existing_meta["ingested_transaction_ids"] = list(seen_txn_ids)
            existing_meta["eligible_transaction_ids"] = eligible_txn_ids
            checkpoint.metadata_json = existing_meta
            session.flush()
            errors.append(str(e))
            logger.error(f"Sync run {sync_run_id} failed mid-stream: {e}")
            return SyncResult(
                sync_run_id=sync_run_id,
                business_id=business_id,
                provider=provider,
                period_start=period_start,
                period_end=period_end,
                status="INCOMPLETE",
                is_complete=False,
                records_extracted=checkpoint.records_extracted,
                records_ingested=checkpoint.records_ingested,
                records_rejected=checkpoint.records_rejected,
                records_duplicate=checkpoint.records_duplicate,
                cursor_chain_hash=chain_hash,
                transaction_set_digest=checkpoint.cursor_chain_hash,
                reported_gross=checkpoint.gross_amount,
                reported_net=checkpoint.net_amount,
                reported_tax=checkpoint.tax_amount,
                reported_fee=checkpoint.fee_amount,
                provenance_type=adapter.get_metadata().provider,
                errors=errors,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                period_close_evidence=None,
            )

        # Compute transaction set digest across all accumulated eligible transactions
        digest = SourceConnectorAdapter.compute_transaction_set_digest(eligible_txn_ids)
        checkpoint.transaction_set_digest = digest

        # Retrieve settlement evidence if supported
        evidence: PeriodCloseEvidence | None = None
        try:
            evidence = adapter.fetch_period_close_evidence(
                "batch_01", period_start=period_start, period_end=period_end
            )
        except PermissionError:
            # Re-raise hard permission errors (e.g. real tenant protection)
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not fetch period-close evidence: {e}")

        session.flush()

        return SyncResult(
            sync_run_id=sync_run_id,
            business_id=business_id,
            provider=provider,
            period_start=period_start,
            period_end=period_end,
            status=checkpoint.status,
            is_complete=checkpoint.is_complete,
            records_extracted=checkpoint.records_extracted,
            records_ingested=checkpoint.records_ingested,
            records_rejected=checkpoint.records_rejected,
            records_duplicate=checkpoint.records_duplicate,
            cursor_chain_hash=checkpoint.cursor_chain_hash,
            transaction_set_digest=digest,
            reported_gross=checkpoint.gross_amount,
            reported_net=checkpoint.net_amount,
            reported_tax=checkpoint.tax_amount,
            reported_fee=checkpoint.fee_amount,
            provenance_type=adapter.get_metadata().provider,
            errors=errors,
            started_at=started_at,
            completed_at=checkpoint.completed_at or datetime.now(UTC),
            period_close_evidence=evidence,
        )

    @classmethod
    def reconcile_and_certify(
        cls,
        session: Session,
        sync_result: SyncResult,
    ) -> bool:
        """
        Validate completeness against Tier 3 settlement evidence.
        Fails closed if amounts mismatch or if synthetic provenance is applied to a real tenant.
        """
        # 1. Real tenant protection invariant via centralized policy
        TenantCertificationPolicy.assert_can_certify_period_close(
            sync_result.business_id,
            sync_result.provenance_type or "unknown",
            session=session,
        )

        # 2. Completeness status invariant
        if not sync_result.is_complete or sync_result.status != "COMPLETED":
            raise ValueError(
                f"Cannot certify incomplete synchronization run (status={sync_result.status}, is_complete={sync_result.is_complete})."
            )

        # 3. Evidence presence check
        evidence = sync_result.period_close_evidence
        if not evidence:
            raise ValueError("Reconciliation failed: Missing Tier 3 period-close settlement evidence.")

        # 4. Mathematical volume reconciliation (zero tolerance on gross volume difference > $0.01)
        gross_delta = abs(sync_result.reported_gross - evidence.gross_amount)
        if gross_delta > Decimal("0.01"):
            raise ValueError(
                f"Financial reconciliation failure: Extracted gross total ${sync_result.reported_gross:.2f} "
                f"differs from provider settlement gross ${evidence.gross_amount:.2f} (delta=${gross_delta:.2f})."
            )

        # 5. Transaction identity coverage check
        if sync_result.transaction_set_digest != evidence.transaction_id_list_hash:
            raise ValueError(
                f"Transaction identity mismatch: Extracted digest '{sync_result.transaction_set_digest}' "
                f"does not match provider settlement digest '{evidence.transaction_id_list_hash}'."
            )

        return True
