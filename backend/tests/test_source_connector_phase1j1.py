"""
NEXUS Phase 1J.1 — Source Connector Adapter & Synthetic Adapter Unit Tests.

Validates:
1. SourceConnectorAdapter interface compliance and deterministic hash utilities.
2. SyntheticSourceAdapter generation determinism, customer linkage, and line item fidelity.
3. Pagination cursor chaining and terminal page detection.
4. Health check diagnostics and simulated status classifications.
5. Timing-safe HMAC webhook signature generation and verification.
6. Automated credential refresh simulation.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import pytest

from app.connectors.source_connector_adapter import SourceConnectorAdapter
from app.connectors.synthetic_source_adapter import SyntheticSourceAdapter
from app.schemas.source_sync import ConnectionHealth, ExtractedRecord, ExtractionPage, SourceMetadata

TEST_TENANT_ID = "00000000-0000-0000-0000-000000000001"
TEST_CREDENTIALS = {
    "api_key": "synth_test_key_abc123",
    "webhook_secret": "synth_webhook_secret_xyz789",
}


def test_source_connector_adapter_abstract_enforcement():
    """Verify that SourceConnectorAdapter cannot be instantiated directly without implementations."""
    with pytest.raises(TypeError):
        SourceConnectorAdapter(TEST_CREDENTIALS, TEST_TENANT_ID)  # type: ignore


def test_hash_utilities_determinism():
    """Verify rolling cursor chain hash and sorted transaction set digest calculations."""
    h0 = hashlib.sha256(b"ROOT").hexdigest()
    h1 = SourceConnectorAdapter.compute_cursor_chain_hash(h0, "page_2")
    h2 = SourceConnectorAdapter.compute_cursor_chain_hash(h1, "page_3")
    h_term = SourceConnectorAdapter.compute_cursor_chain_hash(h2, None)

    assert len(h1) == 64
    assert len(h2) == 64
    assert len(h_term) == 64
    assert h1 != h0
    assert h2 != h1

    # Determinism check
    assert SourceConnectorAdapter.compute_cursor_chain_hash(h0, "page_2") == h1

    # Sorted transaction set digest
    txns_a = ["TXN-3", "TXN-1", "TXN-2"]
    txns_b = ["TXN-1", "TXN-2", "TXN-3"]
    digest_a = SourceConnectorAdapter.compute_transaction_set_digest(txns_a)
    digest_b = SourceConnectorAdapter.compute_transaction_set_digest(txns_b)

    assert digest_a == digest_b
    assert len(digest_a) == 64


def test_synthetic_adapter_metadata_and_health():
    """Verify metadata discovery and health reporting on synthetic adapter."""
    adapter = SyntheticSourceAdapter(TEST_CREDENTIALS, TEST_TENANT_ID)

    meta = adapter.get_metadata()
    assert isinstance(meta, SourceMetadata)
    assert meta.provider == "synthetic_sandbox"
    assert meta.supports_period_close is True
    assert meta.default_currency == "USD"
    assert meta.timezone == "UTC"

    # Default healthy check
    health = adapter.check_health()
    assert isinstance(health, ConnectionHealth)
    assert health.is_healthy is True
    assert health.error_classification == "OK"
    assert health.latency_ms > 0

    # Simulated outage health check
    outage_adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, TEST_TENANT_ID, simulate_outage=True
    )
    health_outage = outage_adapter.check_health()
    assert health_outage.is_healthy is False
    assert health_outage.error_classification == "UNREACHABLE"

    # Simulated rate limit health check
    rate_adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, TEST_TENANT_ID, simulate_rate_limit=True
    )
    health_rate = rate_adapter.check_health()
    assert health_rate.is_healthy is False
    assert health_rate.error_classification == "RATE_LIMITED"


def test_synthetic_adapter_seed_determinism():
    """Verify that identical random seeds generate identical transactions and amounts."""
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    adapter_1 = SyntheticSourceAdapter(TEST_CREDENTIALS, TEST_TENANT_ID, seed=123, num_transactions=25)
    adapter_2 = SyntheticSourceAdapter(TEST_CREDENTIALS, TEST_TENANT_ID, seed=123, num_transactions=25)
    adapter_3 = SyntheticSourceAdapter(TEST_CREDENTIALS, TEST_TENANT_ID, seed=999, num_transactions=25)

    txns_1 = list(adapter_1.stream_historical(start, end))
    txns_2 = list(adapter_2.stream_historical(start, end))
    txns_3 = list(adapter_3.stream_historical(start, end))

    assert len(txns_1) == 25
    assert len(txns_2) == 25
    assert len(txns_3) == 25

    # Exactly equal across identical seeds
    for t1, t2 in zip(txns_1, txns_2):
        assert t1.source_transaction_id == t2.source_transaction_id
        assert t1.gross_amount == t2.gross_amount
        assert t1.transaction_date == t2.transaction_date
        assert t1.status == t2.status
        assert len(t1.line_items) == len(t2.line_items)

    # Different seed yields different transactions
    assert txns_1[0].gross_amount != txns_3[0].gross_amount or txns_1[0].customer_source_id != txns_3[0].customer_source_id


def test_synthetic_adapter_cursor_pagination():
    """Verify cursor pagination step-by-step with rolling hash chaining."""
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, TEST_TENANT_ID, seed=42, num_transactions=75, page_size=25
    )

    # Page 1
    p1 = adapter.fetch_transactions_page(start, end, cursor=None, page_size=25)
    assert isinstance(p1, ExtractionPage)
    assert p1.page_number == 1
    assert len(p1.records) == 25
    assert p1.has_more is True
    assert p1.next_cursor == "page_2"

    # Page 2
    p2 = adapter.fetch_transactions_page(start, end, cursor=p1.next_cursor, page_size=25)
    assert p2.page_number == 2
    assert len(p2.records) == 25
    assert p2.has_more is True
    assert p2.next_cursor == "page_3"

    # Page 3 (Terminal page)
    p3 = adapter.fetch_transactions_page(start, end, cursor=p2.next_cursor, page_size=25)
    assert p3.page_number == 3
    assert len(p3.records) == 25
    assert p3.has_more is False
    assert p3.next_cursor is None


def test_synthetic_webhook_signature_verification():
    """Verify HMAC-SHA256 webhook signature validation and tampering detection."""
    adapter = SyntheticSourceAdapter(TEST_CREDENTIALS, TEST_TENANT_ID)
    secret = TEST_CREDENTIALS["webhook_secret"]

    payload = json.dumps({"event": "order.paid", "order_id": "SYNTH_ORD_001"}).encode("utf-8")
    valid_sig = adapter.generate_event_signature(payload, secret)

    # Standard header verification
    headers = {"X-NEXUS-Signature": valid_sig}
    assert adapter.verify_event_signature(headers, payload, secret) is True

    # Stripe-style header format (v1=...)
    stripe_headers = {"Stripe-Signature": f"t=1600000000,v1={valid_sig}"}
    assert adapter.verify_event_signature(stripe_headers, payload, secret) is True

    # Tampered payload
    tampered_payload = json.dumps({"event": "order.paid", "order_id": "SYNTH_ORD_002"}).encode("utf-8")
    assert adapter.verify_event_signature(headers, tampered_payload, secret) is False

    # Tampered signature
    bad_headers = {"X-NEXUS-Signature": "0" * 64}
    assert adapter.verify_event_signature(bad_headers, payload, secret) is False

    # Missing signature header
    assert adapter.verify_event_signature({}, payload, secret) is False


def test_synthetic_credential_expiration_and_refresh():
    """Verify that expired credentials report error and recover via refresh_credentials."""
    adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, TEST_TENANT_ID, simulate_expired_credentials=True
    )

    auth = adapter.get_auth_status()
    assert auth.is_authenticated is False
    assert "expired" in (auth.error_message or "").lower()

    # Streaming fails with PermissionError
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)
    with pytest.raises(PermissionError, match="Invalid or expired OAuth credentials"):
        adapter.fetch_transactions_page(start, end)

    # Refresh credentials
    refreshed = adapter.refresh_credentials()
    assert refreshed is not None
    assert "access_token" in refreshed

    # Re-check auth status
    auth_after = adapter.get_auth_status()
    assert auth_after.is_authenticated is True
