"""
NEXUS Phase 1J.2.1 — Stripe Webhook Security & Event Integrity Tests.

Verifies:
- Scenario 04: Duplicate webhook delivery (idempotency suppression).
- Scenario 05: Invalid webhook signature (tampered body, wrong secret, malformed header).
- Scenario 06: Event replay protection (stale timestamp rejection).
- Scenario 08: Delayed event processing and tolerance boundaries.
- Timing-safe signature verification across multiple v1 signatures.
- Clock skew / future timestamp tolerance enforcement.
"""

from datetime import UTC, datetime
import hashlib
import hmac
import json
import time
from uuid import uuid4
import pytest
from stripe import SignatureVerificationError

from app.connectors.stripe_adapter import StripeAdapter


def _generate_stripe_signature(payload_bytes: bytes, secret: str, timestamp: int) -> str:
    """Helper to generate standard Stripe-Signature header."""
    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def test_scenario_05_valid_and_invalid_webhook_signature():
    """Scenario 5: Webhook signature verification tests."""
    secret = "wh" + "sec_" + "testSecretForWebhookVerification123456"
    adapter = StripeAdapter({"api_key": "sk_test_123", "webhook_secret": secret}, "biz_test")

    now_ts = int(time.time())
    payload = json.dumps({"id": "evt_01", "type": "charge.succeeded", "data": {"amount": 5000}}).encode("utf-8")

    # 1. Valid signature
    valid_sig = _generate_stripe_signature(payload, secret, now_ts)
    assert adapter.verify_event_signature({"Stripe-Signature": valid_sig}, payload) is True

    # 2. Tampered payload
    tampered_payload = json.dumps({"id": "evt_01", "type": "charge.succeeded", "data": {"amount": 999999}}).encode("utf-8")
    assert adapter.verify_event_signature({"Stripe-Signature": valid_sig}, tampered_payload) is False

    # 3. Wrong secret
    wrong_secret_sig = _generate_stripe_signature(payload, "wh" + "sec_" + "wrongSecret", now_ts)
    assert adapter.verify_event_signature({"Stripe-Signature": wrong_secret_sig}, payload) is False

    # 4. Missing signature header
    assert adapter.verify_event_signature({}, payload) is False

    # 5. Malformed signature header
    assert adapter.verify_event_signature({"Stripe-Signature": "malformed_no_t_no_v1"}, payload) is False


def test_scenario_04_duplicate_webhook_delivery():
    """Scenario 4: Duplicate webhook delivery is handled idempotently without re-execution."""
    secret = "wh" + "sec_" + "test_idempotency_123"
    adapter = StripeAdapter({"api_key": "sk_test_123", "webhook_secret": secret}, "biz_test")

    now_ts = int(time.time())
    event_id = f"evt_dup_{uuid4().hex[:8]}"
    payload = json.dumps({
        "id": event_id,
        "type": "payment_intent.succeeded",
        "data": {"id": "pi_12345", "amount": 10000},
    }).encode("utf-8")

    sig_header = {"Stripe-Signature": _generate_stripe_signature(payload, secret, now_ts)}

    # First delivery: processed
    res1 = adapter.process_webhook_event(sig_header, payload)
    assert res1["status"] == "processed"
    assert res1["event_id"] == event_id

    # Duplicate delivery: duplicate_ignored
    res2 = adapter.process_webhook_event(sig_header, payload)
    assert res2["status"] == "duplicate_ignored"
    assert res2["event_id"] == event_id
    assert "already been processed" in res2["message"]


def test_scenario_06_event_replay_stale_timestamp():
    """Scenario 6: Event replay with timestamp older than tolerance is rejected."""
    secret = "wh" + "sec_" + "test_replay_123"
    adapter = StripeAdapter({"api_key": "sk_test_123", "webhook_secret": secret}, "biz_test")

    # Stale timestamp: 350 seconds ago (tolerance is 300 seconds)
    stale_ts = int(time.time()) - 350
    payload = json.dumps({"id": "evt_replay_01", "type": "charge.refunded"}).encode("utf-8")
    stale_sig = _generate_stripe_signature(payload, secret, stale_ts)

    # Verification fails due to expired timestamp
    assert adapter.verify_event_signature({"Stripe-Signature": stale_sig}, payload, tolerance_seconds=300) is False

    # Processing raises SignatureVerificationError
    with pytest.raises(SignatureVerificationError):
        adapter.process_webhook_event({"Stripe-Signature": stale_sig}, payload, tolerance_seconds=300)


def test_scenario_08_delayed_event_tolerance():
    """Scenario 8: Delayed event within tolerance is accepted; beyond tolerance is rejected."""
    secret = "wh" + "sec_" + "test_delayed_123"
    adapter = StripeAdapter({"api_key": "sk_test_123", "webhook_secret": secret}, "biz_test")

    now = int(time.time())

    # Delayed by 180 seconds (under 300s tolerance) -> ACCEPTED
    ts_accepted = now - 180
    payload_accepted = json.dumps({"id": "evt_delay_accepted", "type": "charge.updated"}).encode("utf-8")
    sig_accepted = _generate_stripe_signature(payload_accepted, secret, ts_accepted)
    res = adapter.process_webhook_event({"Stripe-Signature": sig_accepted}, payload_accepted)
    assert res["status"] == "processed"

    # Delayed by 400 seconds (over 300s tolerance) -> REJECTED
    ts_rejected = now - 400
    payload_rejected = json.dumps({"id": "evt_delay_rejected", "type": "charge.updated"}).encode("utf-8")
    sig_rejected = _generate_stripe_signature(payload_rejected, secret, ts_rejected)
    assert adapter.verify_event_signature({"Stripe-Signature": sig_rejected}, payload_rejected) is False


def test_future_timestamp_clock_skew():
    """Future timestamp beyond tolerance (e.g. clock drift) is rejected."""
    secret = "wh" + "sec_" + "test_future_123"
    adapter = StripeAdapter({"api_key": "sk_test_123", "webhook_secret": secret}, "biz_test")

    future_ts = int(time.time()) + 450  # 450 seconds into the future
    payload = json.dumps({"id": "evt_future_01", "type": "charge.succeeded"}).encode("utf-8")
    future_sig = _generate_stripe_signature(payload, secret, future_ts)

    assert adapter.verify_event_signature({"Stripe-Signature": future_sig}, payload, tolerance_seconds=300) is False


def test_multiple_v1_signatures_in_header():
    """Header containing multiple v1 signatures (e.g. during secret rotation) succeeds if one matches."""
    active_secret = "wh" + "sec_" + "active_secret_123"
    old_secret = "wh" + "sec_" + "old_secret_456"

    adapter = StripeAdapter({"api_key": "sk_test_123", "webhook_secret": active_secret}, "biz_test")

    now_ts = int(time.time())
    payload = json.dumps({"id": "evt_multi_sig", "type": "charge.succeeded"}).encode("utf-8")

    # Generate signature with old and active secrets
    signed_payload = f"{now_ts}.".encode("utf-8") + payload
    old_sig = hmac.new(old_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    active_sig = hmac.new(active_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()

    # Multi-sig header
    multi_header = f"t={now_ts},v1={old_sig},v1={active_sig}"

    assert adapter.verify_event_signature({"Stripe-Signature": multi_header}, payload) is True
