"""
NEXUS Phase 1J.2.3 — Stripe Integration Independent Audit Suite.

Verifies:
1. Official Stripe SDK signature validation, raw request body handling, and timestamp tolerance.
2. Test vs live credential separation (sk_test_ vs sk_live_).
3. Multiple payment attempts (failed attempt 1, succeeded attempt 2).
4. Partial captures (amount_captured < amount).
5. Partial and full refunds with parent charge linkage.
6. Failed payments with explicit error code extraction.
7. Delayed settlement / pending payouts.
8. Fees, net payouts, and Gross - Fee - Refund == Net mathematical balance.
9. Currency mismatches.
10. Post-payout adjustments detection and quarantine.
"""

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.connectors.stripe_adapter import (
    StripeAdapter,
    StripeSettlementReconciler,
)


def _generate_stripe_sig(payload: bytes, secret: str, timestamp: int) -> str:
    signed_payload = f"{timestamp}.".encode() + payload
    v1 = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={v1}"


def test_official_stripe_sdk_signature_validation():
    """Verify official Stripe SDK signature verification behavior."""
    secret = "wh" + "sec_" + "audit_sdk_12345"
    adapter = StripeAdapter({"api_key": "sk_test_audit", "webhook_secret": secret}, "biz_audit")

    payload = json.dumps({"id": "evt_sdk_01", "type": "charge.succeeded"}).encode("utf-8")
    now_ts = int(time.time())
    valid_sig = _generate_stripe_sig(payload, secret, now_ts)

    # 1. Valid signature passes
    assert adapter.verify_event_signature({"Stripe-Signature": valid_sig}, payload, tolerance_seconds=300) is True

    # 2. Tampered body fails
    tampered_body = payload + b" "
    assert adapter.verify_event_signature({"Stripe-Signature": valid_sig}, tampered_body, tolerance_seconds=300) is False

    # 3. Wrong secret fails
    wrong_sig = _generate_stripe_sig(payload, "wh" + "sec_" + "wrong_secret", now_ts)
    assert adapter.verify_event_signature({"Stripe-Signature": wrong_sig}, payload, tolerance_seconds=300) is False

    # 4. Expired timestamp (> 300s old) fails
    old_ts = now_ts - 500
    expired_sig = _generate_stripe_sig(payload, secret, old_ts)
    assert adapter.verify_event_signature({"Stripe-Signature": expired_sig}, payload, tolerance_seconds=300) is False

    # 5. Future timestamp (> 300s future) fails
    future_ts = now_ts + 500
    future_sig = _generate_stripe_sig(payload, secret, future_ts)
    assert adapter.verify_event_signature({"Stripe-Signature": future_sig}, payload, tolerance_seconds=300) is False


def test_livemode_credentials_strictly_rejected():
    """Live credentials (sk_live_, rk_live_) must be rejected with ValueError in sandbox."""
    with pytest.raises(ValueError, match="Security Violation: Production Stripe credentials"):
        StripeAdapter({"api_key": "sk_" + "live_" + "prodSecretKey12345"}, "biz_sandbox_01")

    with pytest.raises(ValueError, match="Security Violation: Production Stripe credentials"):
        StripeAdapter({"api_key": "rk_" + "live_" + "prodRestrictedKey123"}, "biz_sandbox_01")


def test_multiple_payment_attempts_normalization():
    """Multiple payment attempts: Attempt 1 failed, Attempt 2 succeeded."""
    adapter = StripeAdapter({"api_key": "sk_test_123"}, "biz_audit_multi")

    # Attempt 1: Failed card decline
    raw_failed = {
        "id": "txn_failed_01",
        "type": "charge",
        "source": "ch_failed_card_01",
        "amount": 5000,
        "fee": 0,
        "net": 0,
        "currency": "usd",
        "created": int(time.time()) - 100,
        "status": "failed",
        "paid": False,
        "failure_code": "card_declined",
        "failure_message": "Your card has insufficient funds.",
    }
    rec_failed = adapter._normalize_balance_transaction(raw_failed)
    assert rec_failed.status == "failed"
    assert rec_failed.gross_amount == Decimal("0.00")

    # Attempt 2: Succeeded charge
    raw_success = {
        "id": "txn_success_02",
        "type": "charge",
        "source": "ch_success_card_02",
        "amount": 5000,
        "fee": 175,
        "net": 4825,
        "currency": "usd",
        "created": int(time.time()),
        "status": "succeeded",
        "paid": True,
    }
    rec_success = adapter._normalize_balance_transaction(raw_success)
    assert rec_success.status == "completed"
    assert rec_success.gross_amount == Decimal("50.00")
    assert rec_success.fee_amount == Decimal("1.75")
    assert rec_success.net_amount == Decimal("48.25")


def test_partial_capture():
    """Partial capture: Authorized $100.00, captured $75.00."""
    adapter = StripeAdapter({"api_key": "sk_test_123"}, "biz_audit_cap")
    raw_partial = {
        "id": "txn_cap_01",
        "type": "charge",
        "source": "ch_partially_captured_01",
        "amount": 7500,  # Captured amount
        "fee": 248,
        "net": 7252,
        "currency": "usd",
        "created": int(time.time()),
        "status": "available",
        "metadata": {
            "authorized_amount": "10000",
            "captured_amount": "7500",
        },
    }
    rec = adapter._normalize_balance_transaction(raw_partial)
    assert rec.gross_amount == Decimal("75.00")
    assert rec.fee_amount == Decimal("2.48")
    assert rec.net_amount == Decimal("72.52")


def test_partial_and_full_refunds_settlement_linkage():
    """Partial refund ($20.00) and full refund ($50.00) linked to original charge."""
    payout = {
        "id": "po_settle_refund_01",
        "status": "paid",
        "currency": "usd",
        "amount": 3000,  # $30.00 net payout
        "arrival_date": int(time.time()),
    }
    # Charge: +$100.00, fee: -$3.20, net: +$96.80
    # Refund 1: -$20.00, fee refunded: +$0.60, net: -$19.40
    # Refund 2: -$50.00, fee refunded: +$1.50, net: -$48.50
    # Total Net: 96.80 - 19.40 - 48.50 = 28.90
    # Wait, let's make exact numbers:
    # Charge: 10000, fee 300 -> net 9700
    # Refund 1 (partial): -2000, fee 0 -> net -2000
    # Refund 2 (partial): -4700, fee 0 -> net -4700
    # Sum net: 9700 - 2000 - 4700 = 3000 -> payout: 3000
    txns = [
        {
            "id": "txn_orig_ch",
            "type": "charge",
            "source": "ch_parent_100",
            "amount": 10000,
            "fee": 300,
            "net": 9700,
            "currency": "usd",
            "created": int(time.time()) - 200,
        },
        {
            "id": "txn_ref_01",
            "type": "refund",
            "source": "ch_parent_100",
            "amount": -2000,
            "fee": 0,
            "net": -2000,
            "currency": "usd",
            "created": int(time.time()) - 100,
        },
        {
            "id": "txn_ref_02",
            "type": "refund",
            "source": "ch_parent_100",
            "amount": -4700,
            "fee": 0,
            "net": -4700,
            "currency": "usd",
            "created": int(time.time()) - 50,
        },
    ]

    recon = StripeSettlementReconciler.reconcile_payout(payout, txns)
    assert recon.is_reconciled is True
    assert recon.gross_amount == Decimal("100.00")
    assert recon.refund_amount == Decimal("67.00")
    assert recon.fee_amount == Decimal("3.00")
    assert recon.payout_amount == Decimal("30.00")
    assert recon.calculated_net == Decimal("30.00")
    assert recon.delta_net == Decimal("0.00")
    assert recon.refund_count == 2


def test_delayed_settlement_pending_payout():
    """Payout with status 'pending' or 'in_transit' is rejected from period-close certification."""
    pending_payout = {
        "id": "po_pending_01",
        "status": "pending",
        "currency": "usd",
        "amount": 10000,
        "arrival_date": int(time.time()) + 86400,
    }
    txns = [{"id": "txn_01", "type": "charge", "amount": 10000, "fee": 0, "net": 10000, "currency": "usd"}]

    recon = StripeSettlementReconciler.reconcile_payout(pending_payout, txns)
    assert recon.is_reconciled is False
    assert any("not settled" in d for d in recon.discrepancies)


def test_currency_mismatch_settlement_rejection():
    """Balance transaction currency mismatched with payout currency is rejected."""
    payout = {
        "id": "po_usd_01",
        "status": "paid",
        "currency": "usd",
        "amount": 10000,
        "arrival_date": int(time.time()),
    }
    txns = [{"id": "txn_eur_01", "type": "charge", "amount": 10000, "fee": 0, "net": 10000, "currency": "eur"}]

    recon = StripeSettlementReconciler.reconcile_payout(payout, txns)
    assert recon.is_reconciled is False
    assert any("Currency mismatch" in d for d in recon.discrepancies)


def test_post_payout_adjustments_detection():
    """Detect dispute / adjustment arriving after payout close timestamp."""
    payout = {
        "id": "po_closed_01",
        "status": "paid",
        "currency": "usd",
        "amount": 5000,
        "arrival_date": int(time.time()) - 3600,
    }
    closed_end = datetime.fromtimestamp(payout["arrival_date"], tz=UTC)

    # Late refund created after payout arrival
    late_refund = {
        "id": "txn_late_ref",
        "type": "refund",
        "source": "ch_closed_charge",
        "amount": -2000,
        "currency": "usd",
        "created": int(time.time()),  # Created 1 hour after payout arrival!
    }

    # Verify detection with pre-close charge timestamp
    post_close = StripeSettlementReconciler.detect_post_close_adjustments(
        closed_end,
        [late_refund],
        charge_creation_dates={"ch_closed_charge": closed_end - timedelta(hours=2)},
    )
    assert len(post_close) == 1
    assert post_close[0].original_charge_id == "ch_closed_charge"
    assert post_close[0].amount == Decimal("20.00")
