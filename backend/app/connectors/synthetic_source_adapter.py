"""
NEXUS Phase 1J.1 — Deterministic Synthetic Sandbox Source Adapter.

Implements a fully configurable, deterministic synthetic upstream commercial platform
for testing pagination, cursor chaining, HMAC webhook security, period-close evidence,
delayed events, duplicate delivery, backfills, and fail-closed safety invariants.
"""

import hashlib
import hmac
import json
import random
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

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


class SyntheticSourceAdapter(SourceConnectorAdapter):
    """
    Deterministic synthetic data source adapter for sandbox rehearsals.

    Generates realistic commercial orders, line items, refunds, and settlement evidence
    while enforcing synthetic provenance and adversarial test simulation hooks.
    """

    def __init__(
        self,
        tenant_credentials: dict[str, Any],
        business_id: str,
        seed: int = 42,
        num_transactions: int = 150,
        page_size: int = 50,
        # Simulation flags for adversarial scenarios
        simulate_page_drop: bool = False,
        simulate_delayed_event: bool = False,
        simulate_out_of_order: bool = False,
        simulate_duplicate_delivery: bool = False,
        simulate_backfill: bool = False,
        simulate_rate_limit: bool = False,
        simulate_outage: bool = False,
        simulate_expired_credentials: bool = False,
        simulate_forged_signature: bool = False,
        simulate_reconciliation_mismatch: bool = False,
    ):
        super().__init__(tenant_credentials, business_id)
        self.seed = seed
        self.num_transactions = num_transactions
        self.page_size = page_size

        # Simulation flags
        self.simulate_page_drop = simulate_page_drop
        self.simulate_delayed_event = simulate_delayed_event
        self.simulate_out_of_order = simulate_out_of_order
        self.simulate_duplicate_delivery = simulate_duplicate_delivery
        self.simulate_backfill = simulate_backfill
        self.simulate_rate_limit = simulate_rate_limit
        self.simulate_outage = simulate_outage
        self.simulate_expired_credentials = simulate_expired_credentials
        self.simulate_forged_signature = simulate_forged_signature
        self.simulate_reconciliation_mismatch = simulate_reconciliation_mismatch

        # Internal generated dataset cache
        self._dataset_cache: list[ExtractedRecord] | None = None
        self._root_chain_hash = hashlib.sha256(b"ROOT").hexdigest()

    def get_auth_status(self) -> ConnectorAuthStatus:
        """Query synthetic authentication status."""
        if self.simulate_expired_credentials:
            return ConnectorAuthStatus(
                is_authenticated=False,
                auth_type="synthetic_sandbox",
                account_id=f"SYNTH_ACCT_{self.business_id[:8]}",
                scopes=["orders:read", "settlements:read"],
                expires_at=datetime.now(UTC) - timedelta(hours=1),
                error_message="OAuth token has expired (simulated)",
            )

        return ConnectorAuthStatus(
            is_authenticated=True,
            auth_type="synthetic_sandbox",
            account_id=f"SYNTH_ACCT_{self.business_id[:8]}",
            scopes=["orders:read", "settlements:read", "webhooks:read"],
            expires_at=datetime.now(UTC) + timedelta(days=30),
            error_message=None,
        )

    def validate_connection(self) -> bool:
        """Validate synthetic connection reachability."""
        if self.simulate_outage:
            raise ConnectionError("Simulated upstream provider outage: connection timeout (504 Gateway Timeout)")
        return not self.simulate_expired_credentials

    def get_metadata(self) -> SourceMetadata:
        """Return provider discovery metadata."""
        return SourceMetadata(
            provider="synthetic_sandbox",
            provider_account_id=f"SYNTH_ACCT_{self.business_id[:8]}",
            source_name="NEXUS Synthetic Sandbox Source Engine",
            supported_sync_modes=["historical", "incremental", "webhook"],
            supports_period_close=True,
            settlement_type="payout",
            default_currency="USD",
            timezone="UTC",
            rate_limit_info={"limit": 100, "remaining": 95, "reset_seconds": 60},
        )

    def check_health(self) -> ConnectionHealth:
        """Return connection health status."""
        if self.simulate_outage:
            return ConnectionHealth(
                is_healthy=False,
                latency_ms=5000.0,
                error_classification="UNREACHABLE",
                message="Simulated upstream network outage",
            )
        if self.simulate_rate_limit:
            return ConnectionHealth(
                is_healthy=False,
                latency_ms=12.0,
                quota_remaining=0,
                error_classification="RATE_LIMITED",
                message="Simulated rate limit exceeded: HTTP 429 Too Many Requests",
            )
        if self.simulate_expired_credentials:
            return ConnectionHealth(
                is_healthy=False,
                latency_ms=25.0,
                error_classification="AUTH_EXPIRED",
                message="Credentials expired",
            )

        return ConnectionHealth(
            is_healthy=True,
            latency_ms=18.5,
            quota_remaining=95,
            error_classification="OK",
            message="Synthetic sandbox connection optimal",
        )

    def _generate_synthetic_records(
        self,
        period_start: datetime,
        period_end: datetime,
    ) -> list[ExtractedRecord]:
        """Generate deterministic synthetic commercial transactions within [period_start, period_end]."""
        if self._dataset_cache is not None:
            return self._dataset_cache

        rng = random.Random(self.seed)
        records: list[ExtractedRecord] = []

        total_span = (period_end - period_start).total_seconds()
        step_seconds = total_span / max(self.num_transactions, 1)

        customer_pool = [
            (f"SYNTH_CUST_{i:04d}", f"synthetic_user_{i:04d}@example.com", f"Customer {i}")
            for i in range(1, 21)
        ]

        skus = [
            ("SKU-WIDGET-01", "Standard Widget", Decimal("19.99")),
            ("SKU-GADGET-02", "Deluxe Gadget", Decimal("49.99")),
            ("SKU-TOOL-03", "Heavy Duty Tool", Decimal("89.99")),
            ("SKU-ACCESSORY-04", "Cleaning Kit", Decimal("9.99")),
        ]

        for i in range(1, self.num_transactions + 1):
            txn_id = f"SYNTH_TXN_{self.business_id[:8]}_{i:05d}"
            txn_number = f"ORD-SYNTH-{i:05d}"

            # Deterministic timestamp within period
            offset = (i - 1) * step_seconds + (rng.random() * (step_seconds * 0.5))
            txn_dt = period_start + timedelta(seconds=min(offset, total_span - 10))

            cust_id, cust_email, cust_name = rng.choice(customer_pool)

            # Determine status: 90% completed, 7% refunded, 3% cancelled
            status_roll = rng.random()
            if status_roll < 0.90:
                status = "completed"
            elif status_roll < 0.97:
                status = "refunded"
            else:
                status = "cancelled"

            num_items = rng.randint(1, 3)
            items: list[ExtractedLineItem] = []
            gross = Decimal("0.00")
            tax = Decimal("0.00")
            discount = Decimal("0.00")

            for item_idx in range(1, num_items + 1):
                sku, title, price = rng.choice(skus)
                qty = rng.randint(1, 2)
                item_total = price * Decimal(qty)
                item_tax = (item_total * Decimal("0.08")).quantize(Decimal("0.01"))
                item_discount = Decimal("0.00")
                if rng.random() < 0.2:
                    item_discount = Decimal("5.00")

                items.append(
                    ExtractedLineItem(
                        line_item_id=f"{txn_id}_ITEM_{item_idx}",
                        sku=sku,
                        title=title,
                        quantity=qty,
                        unit_price=price,
                        total_amount=item_total,
                        discount_amount=item_discount,
                        tax_amount=item_tax,
                    )
                )
                gross += item_total
                tax += item_tax
                discount += item_discount

            net = gross - discount
            fee = (net * Decimal("0.029") + Decimal("0.30")).quantize(Decimal("0.01"))

            payload_raw = json.dumps(
                {"id": txn_id, "gross": str(gross), "status": status, "items": len(items)},
                sort_keys=True,
            )
            raw_hash = hashlib.sha256(payload_raw.encode("utf-8")).hexdigest()

            records.append(
                ExtractedRecord(
                    source_transaction_id=txn_id,
                    transaction_number=txn_number,
                    customer_source_id=cust_id,
                    customer_email=cust_email,
                    customer_name=cust_name,
                    transaction_date=txn_dt,
                    status=status,
                    currency="USD",
                    gross_amount=gross,
                    discount_amount=discount,
                    tax_amount=tax,
                    net_amount=net,
                    fee_amount=fee,
                    line_items=items,
                    raw_payload_hash=raw_hash,
                    provenance_type="synthetic_sandbox",
                    event_type="order.paid" if status == "completed" else f"order.{status}",
                )
            )

        # Simulation Hooks:
        if self.simulate_delayed_event and records:
            # Shift the last record timestamp to slightly after period_end
            delayed_record = records[-1].model_copy()
            delayed_record.transaction_date = period_end + timedelta(minutes=15)
            delayed_record.source_transaction_id = f"{delayed_record.source_transaction_id}_DELAYED"
            records[-1] = delayed_record

        if self.simulate_backfill and records:
            # Inject a record with created_at earlier than period_start
            backfill_record = records[0].model_copy()
            backfill_record.transaction_date = period_start - timedelta(days=2)
            backfill_record.source_transaction_id = f"SYNTH_TXN_{self.business_id[:8]}_BACKFILL"
            records.insert(0, backfill_record)

        if self.simulate_duplicate_delivery and len(records) > 2:
            # Duplicate the second record
            dup = records[1].model_copy()
            records.insert(2, dup)

        if self.simulate_out_of_order and len(records) > 5:
            # Swap records to make them out of chronological order
            records[1], records[4] = records[4], records[1]

        self._dataset_cache = records
        return records

    def fetch_transactions_page(
        self,
        period_start: datetime,
        period_end: datetime,
        cursor: str | None = None,
        page_size: int | None = None,
        previous_chain_hash: str | None = None,
    ) -> ExtractionPage:
        """Fetch a single page of synthetic transactions with deterministic cursor pagination."""
        if self.simulate_outage:
            raise ConnectionError("Simulated upstream provider outage: connection timeout (504)")
        if self.simulate_rate_limit:
            raise ValueError("HTTP 429 Too Many Requests: Rate limit exceeded")
        if self.simulate_expired_credentials:
            raise PermissionError("HTTP 401 Unauthorized: Invalid or expired OAuth credentials")

        eff_page_size = page_size or self.page_size
        records = self._generate_synthetic_records(period_start, period_end)

        # Determine start index from cursor (cursor format: "page_{page_num}")
        page_num = 1
        start_idx = 0
        current_chain_hash = previous_chain_hash or self._root_chain_hash

        if cursor:
            try:
                parts = cursor.split("_")
                page_num = int(parts[1])
                start_idx = (page_num - 1) * eff_page_size
            except Exception:
                start_idx = 0

        # Adversarial simulation: drop page 2
        if self.simulate_page_drop and page_num == 2:
            raise ValueError("Simulated unexpected page drop: Upstream returned incomplete page response")

        end_idx = min(start_idx + eff_page_size, len(records))
        page_records = records[start_idx:end_idx]
        has_more = end_idx < len(records)

        next_cursor = f"page_{page_num + 1}" if has_more else None
        chain_hash = self.compute_cursor_chain_hash(current_chain_hash, next_cursor)

        gross_page_sum = sum((r.gross_amount for r in page_records), Decimal("0.00"))

        return ExtractionPage(
            records=page_records,
            page_number=page_num,
            has_more=has_more,
            next_cursor=next_cursor,
            cursor_chain_hash=chain_hash,
            page_records_count=len(page_records),
            gross_page_sum=gross_page_sum,
        )

    def stream_historical(
        self,
        period_start: datetime,
        period_end: datetime,
        checkpoint: SyncCheckpoint | None = None,
    ) -> Iterator[ExtractedRecord]:
        """Stream all synthetic transactions page by page."""
        cursor = checkpoint.current_cursor if checkpoint else None
        chain_hash = checkpoint.cursor_chain_hash if checkpoint else self._root_chain_hash

        while True:
            page = self.fetch_transactions_page(
                period_start, period_end, cursor=cursor, page_size=self.page_size
            )
            yield from page.records
            cursor = page.next_cursor
            if not page.has_more or not cursor:
                break

    def stream_incremental(
        self,
        since: datetime,
        checkpoint: SyncCheckpoint | None = None,
    ) -> Iterator[ExtractedRecord]:
        """Stream incremental transactions updated since the given timestamp."""
        records = self._generate_synthetic_records(since, since + timedelta(days=7))
        for r in records:
            if r.transaction_date >= since:
                yield r

    def fetch_period_close_evidence(
        self,
        period_identifier: str,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> PeriodCloseEvidence | None:
        """
        Return authoritative synthetic period-close evidence (e.g. simulated Payout batch).
        Enforces strict non-negotiable guard: synthetic evidence must never certify a real tenant.
        """
        # Centralized fail-closed guard against real tenant certification
        TenantCertificationPolicy.assert_can_ingest_synthetic(self.business_id, "synthetic")

        if self._dataset_cache is not None:
            records = self._dataset_cache
            start = period_start or min(r.transaction_date for r in records)
            end = period_end or max(r.transaction_date for r in records)
        else:
            now = datetime.now(UTC)
            start = period_start or (now - timedelta(days=30))
            end = period_end or (now - timedelta(days=1))
            records = self._generate_synthetic_records(start, end)

        eligible = [r for r in records if r.status in ("completed", "refunded", "shipped", "paid")]

        total_gross = sum((r.gross_amount for r in eligible), Decimal("0.00"))
        total_net = sum((r.net_amount for r in eligible), Decimal("0.00"))
        total_tax = sum((r.tax_amount for r in eligible), Decimal("0.00"))
        total_fee = sum((r.fee_amount for r in eligible), Decimal("0.00"))

        if self.simulate_reconciliation_mismatch:
            # Artificially alter net by $0.05 to trigger mathematical reconciliation failure
            total_net += Decimal("0.05")

        txn_ids = [r.source_transaction_id for r in eligible]
        digest = self.compute_transaction_set_digest(txn_ids)

        payout_id = f"SYNTH_PAYOUT_{self.business_id[:8]}_{period_identifier}"
        raw_evidence = {
            "payout_id": payout_id,
            "status": "paid",
            "batch_closed_at": end.isoformat(),
            "transaction_count": len(eligible),
            "reported_net": str(total_net),
            "reported_gross": str(total_gross),
        }

        # Generate HMAC signature
        secret = self.credentials.get("webhook_secret", "synthetic_test_secret_key_12345")
        raw_bytes = json.dumps(raw_evidence, sort_keys=True).encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()

        if self.simulate_forged_signature:
            signature = "0" * 64

        return PeriodCloseEvidence(
            provider="synthetic_sandbox",
            settlement_id=payout_id,
            settlement_status="paid",
            settlement_date=end + timedelta(hours=2),
            period_start=start,
            period_end=end,
            currency="USD",
            gross_amount=total_gross,
            net_amount=total_net,
            tax_amount=total_tax,
            fee_amount=total_fee,
            transaction_count=len(eligible),
            transaction_id_list_hash=digest,
            provider_signature=signature,
            raw_evidence=raw_evidence,
            provenance_type="synthetic_sandbox",
            trust_tier="tier3_source_evidence",
        )

    def generate_event_signature(self, body_bytes: bytes, secret: str) -> str:
        """Helper to generate valid HMAC-SHA256 signature for synthetic webhook events."""
        return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

    def verify_event_signature(
        self,
        headers: dict[str, str],
        body_bytes: bytes,
        secret: str,
    ) -> bool:
        """Validate HMAC-SHA256 signature from headers against payload bytes."""
        sig_header = (
            headers.get("X-NEXUS-Signature")
            or headers.get("Stripe-Signature")
            or headers.get("X-Shopify-Hmac-Sha256")
        )
        if not sig_header:
            return False

        # Support signature formats: direct hex or 'v1=hex'
        sig_hex = sig_header.split("v1=")[-1].strip() if "v1=" in sig_header else sig_header.strip()

        expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig_hex.lower(), expected.lower())

    def refresh_credentials(self) -> dict[str, Any] | None:
        """Perform simulated token refresh."""
        if self.simulate_expired_credentials:
            # Simulate recovery
            self.simulate_expired_credentials = False
            return {
                "access_token": f"synth_token_refreshed_{uuid4().hex[:12]}",
                "refresh_token": f"synth_refresh_{uuid4().hex[:12]}",
                "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            }
        return None
