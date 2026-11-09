"""
NEXUS Phase 1J.2.1 — Stripe Test Mode Sandbox Adapter.

Provides:
1. StripeEvidenceTier: Categorizes upstream data into explicit evidentiary tiers:
   - Tier 1: Stripe-authenticated API balance transaction records.
   - Tier 2: Stripe-signed webhook events.
   - Tier 3: Stripe payout & balance transaction settlement reconciliation.
   - Tier 4: Merchant-wide accounting period close (external to Stripe).
2. StripeSettlementReconciler: Standalone settlement reconciliation layer:
   - Reconciles Stripe Payouts against balance transactions (Gross, Fees, Refunds, Net).
   - Enforces currency and payout status invariants.
   - Preserves refund-to-charge linkage.
   - Detects and quarantines post-close adjustments to prevent silent mutation of closed periods.
3. StripeAdapter: Implementation of SourceConnectorAdapter for Stripe Test Mode:
   - Authenticated with Stripe Test Mode API keys (sk_test_... / rk_test_...).
   - Rejects live production keys (sk_live_ / rk_live_) in sandbox context.
   - Cursor-based pagination with deterministic rolling cursor chain hashes.
   - Timing-safe Stripe-Signature webhook verification with timestamp tolerance.
   - Webhook idempotency and event replay protection.
   - Strict fail-closed isolation preventing test-mode certifications of real tenants.
"""

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

import stripe
from pydantic import BaseModel, Field
from stripe import SignatureVerificationError

from app.connectors.source_connector_adapter import SourceConnectorAdapter
from app.schemas.source_sync import (
    ConnectionHealth,
    ConnectorAuthStatus,
    ExtractedLineItem,
    ExtractedRecord,
    ExtractionPage,
    PeriodCloseEvidence,
    SourceMetadata,
    SyncCheckpoint,
)
from app.services.tenant_certification_policy import TenantCertificationPolicy

logger = logging.getLogger(__name__)


# Pinned Stripe API Version (Semiannual Major Release Schedule)
DEFAULT_STRIPE_API_VERSION = "2026-10-28.endive"
SUPPORTED_STRIPE_API_VERSIONS: set[str] = {
    "2026-10-28.endive",
    "2024-06-20",
}


class StripeEvidenceTier(str, Enum):
    """
    Explicit evidentiary classification for Stripe source data.
    Stripe payment evidence proves payment gateway settlement; it does NOT
    prove completeness across a merchant's entire business or sales channels.
    """
    TIER1_AUTHENTICATED_API = "tier1_authenticated_api"
    TIER2_SIGNED_WEBHOOK = "tier2_signed_webhook"
    TIER3_PAYOUT_SETTLEMENT = "tier3_payout_settlement"
    TIER4_ACCOUNTING_CLOSE = "tier4_accounting_close"


class PostCloseAdjustment(BaseModel):
    """Represents a financial adjustment (e.g. refund, chargeback) arriving after period close."""
    original_charge_id: str
    refund_transaction_id: str
    amount: Decimal
    currency: str
    adjustment_date: datetime
    closed_period_end: datetime
    description: str = "Post-close adjustment quarantined to protect closed period integrity."


class StripePayoutReconciliation(BaseModel):
    """Structured reconciliation between a Stripe Payout and its underlying balance transactions."""
    payout_id: str
    status: str
    currency: str
    arrival_date: datetime
    payout_amount: Decimal
    gross_amount: Decimal
    fee_amount: Decimal
    refund_amount: Decimal
    calculated_net: Decimal
    delta_net: Decimal
    is_reconciled: bool
    transaction_count: int
    refund_count: int
    discrepancies: list[str] = Field(default_factory=list)
    evidence_tier: StripeEvidenceTier = StripeEvidenceTier.TIER3_PAYOUT_SETTLEMENT
    reconciled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StripeSettlementReconciler:
    """
    Independent reconciliation engine for Stripe Payouts and Balance Transactions.
    Verifies that Gross - Fees - Refunds == Payout Net.
    """

    @classmethod
    def reconcile_payout(
        cls,
        payout: dict[str, Any],
        balance_transactions: list[dict[str, Any]],
    ) -> StripePayoutReconciliation:
        """
        Reconcile a Stripe payout dictionary against a list of Stripe balance transaction dictionaries.
        """
        payout_id = payout.get("id", "po_unknown")
        status = payout.get("status", "pending")
        raw_currency = payout.get("currency", "usd").upper()

        # Payout amount in dollars
        raw_payout_amt = payout.get("amount", 0)
        payout_amount = (
            raw_payout_amt if isinstance(raw_payout_amt, Decimal)
            else Decimal(raw_payout_amt) / Decimal(100)
        )

        arr_raw = payout.get("arrival_date") or payout.get("created", int(time.time()))
        if isinstance(arr_raw, (int, float)):
            arrival_date = datetime.fromtimestamp(arr_raw, tz=UTC)
        elif isinstance(arr_raw, datetime):
            arrival_date = arr_raw if arr_raw.tzinfo else arr_raw.replace(tzinfo=UTC)
        else:
            arrival_date = datetime.now(UTC)

        discrepancies: list[str] = []

        # Tally balance transactions
        gross_total = Decimal("0.00")
        fee_total = Decimal("0.00")
        refund_total = Decimal("0.00")
        refund_count = 0
        tx_count = len(balance_transactions)

        for txn in balance_transactions:
            txn_cur = txn.get("currency", "usd").upper()
            if txn_cur != raw_currency:
                discrepancies.append(
                    f"Currency mismatch on transaction {txn.get('id')}: {txn_cur} != {raw_currency}"
                )

            amt_cents = txn.get("amount", 0)
            fee_cents = txn.get("fee", 0)
            txn_type = txn.get("type", "charge")

            amt_dec = (
                amt_cents if isinstance(amt_cents, Decimal)
                else Decimal(amt_cents) / Decimal(100)
            )
            fee_dec = (
                fee_cents if isinstance(fee_cents, Decimal)
                else Decimal(fee_cents) / Decimal(100)
            )

            fee_total += abs(fee_dec)

            if txn_type == "refund" or amt_dec < Decimal("0.00"):
                refund_total += abs(amt_dec)
                refund_count += 1
            else:
                gross_total += amt_dec

        calculated_net = gross_total - fee_total - refund_total
        delta_net = abs(calculated_net - payout_amount)

        # Invariant 1: Mathematical reconciliation (tolerance $0.01)
        if delta_net > Decimal("0.01"):
            discrepancies.append(
                f"Net settlement mismatch: Calculated net ${calculated_net:.2f} differs from payout amount ${payout_amount:.2f} (delta=${delta_net:.2f})"
            )

        # Invariant 2: Payout status must be paid
        if status.lower() != "paid":
            discrepancies.append(f"Payout is not settled: status is '{status}', expected 'paid'.")

        is_reconciled = len(discrepancies) == 0

        return StripePayoutReconciliation(
            payout_id=payout_id,
            status=status,
            currency=raw_currency,
            arrival_date=arrival_date,
            payout_amount=payout_amount,
            gross_amount=gross_total,
            fee_amount=fee_total,
            refund_amount=refund_total,
            calculated_net=calculated_net,
            delta_net=delta_net,
            is_reconciled=is_reconciled,
            transaction_count=tx_count,
            refund_count=refund_count,
            discrepancies=discrepancies,
            evidence_tier=StripeEvidenceTier.TIER3_PAYOUT_SETTLEMENT,
        )

    @classmethod
    def link_refunds_to_charges(
        cls,
        balance_transactions: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Group refunds by originating charge/source ID.
        """
        charge_to_refunds: dict[str, list[dict[str, Any]]] = {}
        for txn in balance_transactions:
            if txn.get("type") == "refund":
                # Look for source charge ID in source or metadata
                charge_id = txn.get("source") or txn.get("charge") or txn.get("metadata", {}).get("charge_id")
                if charge_id:
                    charge_to_refunds.setdefault(charge_id, []).append(txn)
        return charge_to_refunds

    @classmethod
    def detect_post_close_adjustments(
        cls,
        closed_period_end: datetime,
        balance_transactions: list[dict[str, Any]],
        charge_creation_dates: dict[str, datetime] | None = None,
    ) -> list[PostCloseAdjustment]:
        """
        Detect refunds or chargebacks occurring after `closed_period_end` that belong to charges
        originating within or before the closed period.
        Prevents silent mutation of closed periods.
        """
        adjustments: list[PostCloseAdjustment] = []
        closed_utc = closed_period_end if closed_period_end.tzinfo else closed_period_end.replace(tzinfo=UTC)

        for txn in balance_transactions:
            if txn.get("type") == "refund":
                created_raw = txn.get("created", int(time.time()))
                refund_dt = datetime.fromtimestamp(created_raw, tz=UTC) if isinstance(created_raw, (int, float)) else created_raw

                charge_id = txn.get("source") or txn.get("charge") or ""
                charge_dt = (charge_creation_dates or {}).get(charge_id)

                # If the refund occurs AFTER period close, but belongs to a charge AT OR BEFORE period close
                if refund_dt > closed_utc and charge_dt and charge_dt <= closed_utc:
                    amt = Decimal(abs(txn.get("amount", 0))) / Decimal(100)
                    adjustments.append(
                        PostCloseAdjustment(
                            original_charge_id=charge_id,
                            refund_transaction_id=txn.get("id", "txn_unknown"),
                            amount=amt,
                            currency=txn.get("currency", "usd").upper(),
                            adjustment_date=refund_dt,
                            closed_period_end=closed_utc,
                        )
                    )
        return adjustments


class StripeAdapter(SourceConnectorAdapter):
    """
    NEXUS Source Connector Adapter for Stripe Test Mode.

    Provides:
    - Test Mode authentication and API key validation.
    - Balance transaction synchronization (charges, refunds, transfers).
    - Cursor-based deterministic pagination with SHA-256 rolling chain hash.
    - Timing-safe HMAC webhook signature verification (Stripe-Signature).
    - Webhook event idempotency and duplicate delivery handling.
    - Rate-limit (HTTP 429) backoff and classification.
    - Payout settlement reconciliation evidence retrieval.
    """

    def __init__(
        self,
        tenant_credentials: dict[str, Any],
        business_id: str,
        stripe_client: Any | None = None,
        max_retries: int = 3,
        rate_limit_backoff_sec: float = 0.05,
    ):
        super().__init__(tenant_credentials, business_id)
        self.api_key = tenant_credentials.get("api_key", "").strip()
        self.webhook_secret = tenant_credentials.get("webhook_secret", "").strip()
        self.account_id = tenant_credentials.get("account_id")
        self.api_version = tenant_credentials.get("api_version") or DEFAULT_STRIPE_API_VERSION
        self.stripe_client = stripe_client
        self.max_retries = max_retries
        self.rate_limit_backoff_sec = rate_limit_backoff_sec

        # Strict Sandbox Security Constraint: Prohibit Live credentials
        if self.api_key.startswith("sk_live_") or self.api_key.startswith("rk_live_"):
            raise ValueError(
                "Security Violation: Production Stripe credentials ('livemode') are strictly prohibited "
                "in sandbox adapter. Must use Test Mode keys starting with 'sk_test_' or 'rk_test_'."
            )

        # Webhook event idempotency memory
        self._processed_webhook_event_ids: set[str] = set()

    def _get_stripe_client(self) -> stripe.StripeClient:
        """Instantiate official StripeClient pinned to the configured API version."""
        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "stripe_version": self.api_version,
        }
        if self.account_id:
            kwargs["stripe_account"] = self.account_id
        return stripe.StripeClient(**kwargs)

    def get_auth_status(self) -> ConnectorAuthStatus:
        """Validate Stripe Test Mode key syntax and status."""
        if not self.api_key:
            return ConnectorAuthStatus(
                is_authenticated=False,
                auth_type="api_key_test_mode",
                account_id=self.account_id,
                scopes=[],
                error_message="Missing Stripe API key.",
            )

        if not (self.api_key.startswith("sk_test_") or self.api_key.startswith("rk_test_")):
            return ConnectorAuthStatus(
                is_authenticated=False,
                auth_type="api_key_test_mode",
                account_id=self.account_id,
                scopes=[],
                error_message="Invalid Stripe API key format: must begin with sk_test_ or rk_test_.",
            )

        return ConnectorAuthStatus(
            is_authenticated=True,
            auth_type="api_key_test_mode",
            account_id=self.account_id or f"acct_test_{self.business_id[:8]}",
            scopes=[
                "balance_transactions:read",
                "charges:read",
                "payouts:read",
                "refunds:read",
                "webhooks:verify",
            ],
            last_verified_at=datetime.now(UTC),
        )

    def validate_connection(self) -> bool:
        """Verify upstream platform connectivity and credentials."""
        status = self.get_auth_status()
        if not status.is_authenticated:
            return False

        if self.stripe_client is not None:
            if hasattr(self.stripe_client, "validate_connection"):
                return bool(self.stripe_client.validate_connection())
            return True

        try:
            client = self._get_stripe_client()
            client.balance.retrieve()
            return True
        except Exception as e:
            logger.warning(f"Stripe connection validation failed: {e}")
            return False

    def get_metadata(self) -> SourceMetadata:
        """Return discovery metadata for Stripe sandbox."""
        return SourceMetadata(
            provider="stripe",
            provider_account_id=self.account_id or f"acct_stripe_{self.business_id[:8]}",
            source_name="Stripe Payments Sandbox (Test Mode)",
            supported_sync_modes=["historical", "incremental", "webhook"],
            supports_period_close=True,
            settlement_type="payout",
            default_currency="USD",
            timezone="UTC",
            rate_limit_info={"tier": "test_mode_sandbox", "limit_per_sec": 25},
        )

    def check_health(self) -> ConnectionHealth:
        """Check live connection latency and rate limit status."""
        start_t = time.perf_counter()
        if self.stripe_client is not None:
            if hasattr(self.stripe_client, "check_health"):
                return self.stripe_client.check_health()
            elapsed_ms = (time.perf_counter() - start_t) * 1000
            return ConnectionHealth(
                is_healthy=True,
                latency_ms=elapsed_ms,
                quota_remaining=100,
                error_classification="OK",
                message="Stripe mock test client healthy.",
            )

        try:
            client = self._get_stripe_client()
            client.balance.retrieve()
            elapsed_ms = (time.perf_counter() - start_t) * 1000
            return ConnectionHealth(
                is_healthy=True,
                latency_ms=elapsed_ms,
                quota_remaining=99,
                error_classification="OK",
                message="Stripe API responsive.",
            )
        except stripe.RateLimitError:
            elapsed_ms = (time.perf_counter() - start_t) * 1000
            return ConnectionHealth(
                is_healthy=False,
                latency_ms=elapsed_ms,
                quota_remaining=0,
                error_classification="RATE_LIMITED",
                message="Stripe API rate limit exceeded (HTTP 429).",
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_t) * 1000
            return ConnectionHealth(
                is_healthy=False,
                latency_ms=elapsed_ms,
                error_classification="UNREACHABLE",
                message=f"Stripe health check failed: {e}",
            )

    def fetch_transactions_page(
        self,
        period_start: datetime,
        period_end: datetime,
        cursor: str | None = None,
        page_size: int = 100,
        previous_chain_hash: str | None = None,
    ) -> ExtractionPage:
        """
        Fetch a single paginated page of Stripe balance transactions within [period_start, period_end].
        Implements cursor chain hashing and rate limit backoff.
        """
        prev_hash = previous_chain_hash or hashlib.sha256(b"ROOT").hexdigest()

        # Handle client call with backoff retry
        raw_items: list[dict[str, Any]] = []
        has_more = False

        attempts = 0
        while attempts < self.max_retries:
            try:
                if self.stripe_client is not None:
                    page_data = self.stripe_client.fetch_balance_transactions(
                        period_start=period_start,
                        period_end=period_end,
                        cursor=cursor,
                        page_size=page_size,
                    )
                    raw_items = page_data.get("data", [])
                    has_more = page_data.get("has_more", False)
                    break
                else:
                    p_start_sec = int(period_start.timestamp())
                    p_end_sec = int(period_end.timestamp())

                    params: dict[str, Any] = {
                        "created": {"gte": p_start_sec, "lte": p_end_sec},
                        "limit": page_size,
                    }
                    if cursor:
                        params["starting_after"] = cursor

                    client = self._get_stripe_client()
                    resp = client.balance_transactions.list(params=params)
                    raw_items = [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in resp.data]
                    has_more = resp.has_more
                    break
            except stripe.RateLimitError as e:
                attempts += 1
                if attempts >= self.max_retries:
                    raise RuntimeError(f"Stripe rate limit exceeded after {attempts} retries: {e}")
                time.sleep(self.rate_limit_backoff_sec * (2 ** attempts))
            except Exception as e:
                raise RuntimeError(f"Stripe API error fetching balance transactions: {e}")

        # Normalize balance transactions to ExtractedRecord
        records: list[ExtractedRecord] = []
        for item in raw_items:
            rec = self._normalize_balance_transaction(item)
            records.append(rec)

        # Pagination cursor progression
        next_cursor = raw_items[-1]["id"] if has_more and raw_items else None
        current_chain_hash = self.compute_cursor_chain_hash(prev_hash, next_cursor)

        gross_sum = sum((r.gross_amount for r in records), Decimal("0.00"))

        return ExtractionPage(
            records=records,
            page_number=1,  # Cursor pagination does not rely on absolute page numbers
            has_more=has_more,
            next_cursor=next_cursor,
            cursor_chain_hash=current_chain_hash,
            page_records_count=len(records),
            gross_page_sum=gross_sum,
        )

    def _normalize_balance_transaction(self, item: dict[str, Any]) -> ExtractedRecord:
        """
        Map a Stripe balance transaction dictionary into a typed NEXUS ExtractedRecord.
        """
        tx_id = item.get("id", f"txn_{uuid4().hex[:12]}")
        source_id = item.get("source") or tx_id
        tx_type = item.get("type", "charge")

        raw_amt = item.get("amount", 0)
        raw_fee = item.get("fee", 0)
        raw_net = item.get("net", raw_amt - raw_fee)

        amt_dec = Decimal(abs(raw_amt)) / Decimal(100)
        fee_dec = Decimal(abs(raw_fee)) / Decimal(100)
        net_dec = Decimal(raw_net) / Decimal(100)

        # Determine transaction date
        created_raw = item.get("created", int(time.time()))
        if isinstance(created_raw, (int, float)):
            txn_dt = datetime.fromtimestamp(created_raw, tz=UTC)
        elif isinstance(created_raw, datetime):
            txn_dt = created_raw if created_raw.tzinfo else created_raw.replace(tzinfo=UTC)
        else:
            txn_dt = datetime.now(UTC)

        # Status mapping
        if tx_type == "refund" or raw_amt < 0:
            status = "refunded"
        elif item.get("status") == "available" or item.get("status") == "succeeded":
            status = "completed"
        elif item.get("status") == "failed" or item.get("paid") is False:
            status = "failed"
            amt_dec = Decimal("0.00")
            net_dec = Decimal("0.00")
        else:
            status = "pending"

        currency = item.get("currency", "usd").upper()

        # Customer and reference information
        metadata = item.get("metadata") or {}
        customer_id = metadata.get("customer_id") or item.get("customer")
        customer_email = metadata.get("customer_email") or metadata.get("email")

        # Construct single line item representation
        line_items = [
            ExtractedLineItem(
                line_item_id=f"li_{tx_id}",
                title=item.get("description") or f"Stripe {tx_type.capitalize()}",
                quantity=1,
                unit_price=amt_dec,
                total_amount=amt_dec,
            )
        ]

        payload_bytes = json.dumps(item, sort_keys=True).encode("utf-8")
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()

        return ExtractedRecord(
            source_transaction_id=tx_id,
            transaction_number=source_id,
            customer_source_id=customer_id,
            customer_email=customer_email,
            transaction_date=txn_dt,
            status=status,
            currency=currency,
            gross_amount=amt_dec,
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            net_amount=net_dec,
            fee_amount=fee_dec,
            line_items=line_items,
            raw_payload_hash=payload_hash,
            provenance_type="stripe_test_mode",
            event_type=f"stripe.balance_transaction.{tx_type}",
        )

    def stream_historical(
        self,
        period_start: datetime,
        period_end: datetime,
        checkpoint: SyncCheckpoint | None = None,
    ) -> Iterator[ExtractedRecord]:
        """
        Stream all historical balance transactions sequentially within [period_start, period_end].
        """
        cursor = checkpoint.current_cursor if checkpoint else None
        chain_hash = checkpoint.cursor_chain_hash if checkpoint else hashlib.sha256(b"ROOT").hexdigest()

        while True:
            page = self.fetch_transactions_page(
                period_start=period_start,
                period_end=period_end,
                cursor=cursor,
                page_size=100,
                previous_chain_hash=chain_hash,
            )

            for record in page.records:
                yield record

            cursor = page.next_cursor
            chain_hash = page.cursor_chain_hash

            if checkpoint:
                checkpoint.current_cursor = cursor
                checkpoint.cursor_chain_hash = chain_hash
                checkpoint.records_extracted += page.page_records_count

            if not page.has_more or not cursor:
                if checkpoint:
                    checkpoint.is_complete = True
                    checkpoint.status = "COMPLETED"
                break

    def stream_incremental(
        self,
        since: datetime,
        checkpoint: SyncCheckpoint | None = None,
    ) -> Iterator[ExtractedRecord]:
        """
        Stream balance transactions created since the specified timestamp up to the current time.
        """
        now = datetime.now(UTC)
        yield from self.stream_historical(period_start=since, period_end=now, checkpoint=checkpoint)

    def fetch_period_close_evidence(
        self,
        period_identifier: str,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> PeriodCloseEvidence | None:
        """
        Retrieve Tier 3 Stripe Payout settlement evidence for the specified period.
        """
        # Centralized real tenant protection
        TenantCertificationPolicy.assert_can_ingest_synthetic(self.business_id, "stripe_test_mode")

        p_start = period_start or (datetime.now(UTC) - timedelta(days=30))
        p_end = period_end or datetime.now(UTC)

        payout: dict[str, Any]
        txns: list[dict[str, Any]]

        if self.stripe_client is not None:
            payout = self.stripe_client.get_payout(period_identifier)
            txns = self.stripe_client.get_payout_transactions(period_identifier)
        else:
            try:
                client = self._get_stripe_client()
                payout_obj = client.payouts.retrieve(period_identifier)
                payout = payout_obj.to_dict() if hasattr(payout_obj, "to_dict") else dict(payout_obj)
                # Fetch balance transactions for this payout
                resp = client.balance_transactions.list(params={"payout": period_identifier, "limit": 100})
                txns = [t.to_dict() if hasattr(t, "to_dict") else dict(t) for t in resp.data]
            except Exception as e:
                logger.warning(f"Could not retrieve Stripe payout '{period_identifier}': {e}")
                return None

        # Execute reconciliation
        recon = StripeSettlementReconciler.reconcile_payout(payout, txns)
        if not recon.is_reconciled:
            logger.warning(f"Stripe payout '{period_identifier}' reconciliation discrepancies: {recon.discrepancies}")

        tx_ids = [t.get("id", "") for t in txns if t.get("id")]
        tx_digest = self.compute_transaction_set_digest(tx_ids)

        return PeriodCloseEvidence(
            provider="stripe",
            settlement_id=recon.payout_id,
            settlement_status=recon.status,
            settlement_date=recon.arrival_date,
            period_start=p_start,
            period_end=p_end,
            currency=recon.currency,
            gross_amount=recon.gross_amount,
            net_amount=recon.payout_amount,
            tax_amount=Decimal("0.00"),
            fee_amount=recon.fee_amount,
            transaction_count=recon.transaction_count,
            transaction_id_list_hash=tx_digest,
            raw_evidence={
                "payout": payout,
                "reconciliation": recon.model_dump(mode="json"),
            },
            provenance_type="stripe_test_mode",
            trust_tier="tier3_source_evidence",
        )

    def verify_event_signature(
        self,
        headers: dict[str, str],
        body_bytes: bytes,
        secret: str | None = None,
        tolerance_seconds: int = 300,
    ) -> bool:
        """
        Verify Stripe webhook signature from Stripe-Signature header using official Stripe SDK
        with timing-safe comparison fallback.
        Header format: t=1612345678,v1=5257a869e7...,v0=...
        """
        wh_secret = secret or self.webhook_secret
        if not wh_secret:
            return False

        # Case-insensitive header lookup
        sig_header = None
        for k, v in headers.items():
            if k.lower() == "stripe-signature":
                sig_header = v
                break

        if not sig_header:
            return False

        # Parse timestamp first to enforce bidirectional tolerance window (reject future clock drift or replay)
        parsed_items: dict[str, list[str]] = {}
        for part in sig_header.split(","):
            if "=" in part:
                key, val = part.split("=", 1)
                parsed_items.setdefault(key.strip(), []).append(val.strip())

        t_list = parsed_items.get("t", [])
        v1_list = parsed_items.get("v1", [])

        if not t_list or not v1_list:
            return False

        try:
            timestamp = int(t_list[0])
        except ValueError:
            return False

        now_ts = int(time.time())
        if abs(now_ts - timestamp) > tolerance_seconds:
            logger.warning(f"Stripe webhook timestamp {timestamp} is outside tolerance window ({tolerance_seconds}s).")
            return False

        # Attempt verification via official Stripe SDK
        try:
            payload_str = body_bytes.decode("utf-8")
            stripe.WebhookSignature.verify_header(
                payload_str,
                sig_header,
                wh_secret,
                tolerance=tolerance_seconds,
            )
            return True
        except stripe.SignatureVerificationError as e:
            logger.debug(f"Official Stripe SDK signature verification failed: {e}")
        except Exception:
            pass

        # Fallback to manual timing-safe verification
        signed_payload = f"{timestamp}.".encode() + body_bytes
        expected_sig = hmac.new(
            wh_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        # Timing-safe comparison across all provided v1 signatures
        matched = any(hmac.compare_digest(expected_sig, s) for s in v1_list)
        return matched

    def process_webhook_event(
        self,
        headers: dict[str, str],
        body_bytes: bytes,
        secret: str | None = None,
        tolerance_seconds: int = 300,
        session: Any | None = None,
        worker_id: str = "worker_default",
    ) -> dict[str, Any]:
        """
        Authenticate, deduplicate, and process a Stripe webhook event.
        If a database session is provided, delegates to durable database-backed WebhookInboxService.
        Otherwise falls back to in-memory deduplication.
        """
        if session is not None:
            from app.services.webhook_inbox_service import WebhookInboxService
            return WebhookInboxService.process_inbound_webhook(
                session=session,
                adapter=self,
                headers=headers,
                body_bytes=body_bytes,
                worker_id=worker_id,
            )

        is_valid = self.verify_event_signature(
            headers=headers,
            body_bytes=body_bytes,
            secret=secret,
            tolerance_seconds=tolerance_seconds,
        )
        if not is_valid:
            raise SignatureVerificationError("Invalid Stripe webhook signature or timestamp expired.", "stripe-signature")

        try:
            event_payload = json.loads(body_bytes.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Malformed Stripe webhook JSON payload: {e}")

        event_id = event_payload.get("id")
        if not event_id:
            raise ValueError("Stripe webhook event is missing 'id' attribute.")

        # Idempotency Check: Suppress duplicate deliveries
        if event_id in self._processed_webhook_event_ids:
            return {
                "status": "duplicate_ignored",
                "event_id": event_id,
                "message": f"Webhook event '{event_id}' has already been processed.",
            }

        self._processed_webhook_event_ids.add(event_id)

        return {
            "status": "processed",
            "event_id": event_id,
            "event_type": event_payload.get("type", "unknown"),
            "data": event_payload.get("data", {}),
            "processed_at": datetime.now(UTC).isoformat(),
        }

    def refresh_credentials(self) -> dict[str, Any] | None:
        """
        Stripe standard API keys do not expire automatically.
        For OAuth Connect accounts, refresh logic would return updated tokens.
        """
        return None
