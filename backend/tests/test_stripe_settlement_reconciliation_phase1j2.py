"""
NEXUS Phase 1J.2.1 — Stripe Settlement Reconciliation Tests.

Verifies:
- Scenario 07: Refund after payment and refund-to-charge linkage.
- Scenario 09: Payout reconciliation (Gross - Fees - Refunds == Net Payout).
- Scenario 10: Currency mismatch detection between payout and transactions.
- Payout settlement status validation ('paid' vs 'pending'/'failed').
- Non-destructive post-close adjustment detection (protecting closed periods).
- Evidence tier classification: Stripe payout is Tier 3 Payment Settlement, NOT Tier 4 Accounting Close.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import time
from uuid import uuid4
import pytest

from app.connectors.stripe_adapter import (
    StripeAdapter,
    StripeEvidenceTier,
    StripePayoutReconciliation,
    StripeSettlementReconciler,
)


def test_scenario_09_successful_payout_reconciliation():
    """Scenario 9: Successful payout reconciliation matching Gross - Fees - Refunds == Payout Net."""
    payout = {
        "id": "po_rec_01",
        "amount": 48000,  # $480.00 net payout
        "currency": "usd",
        "status": "paid",
        "arrival_date": int(time.time()),
    }

    balance_txns = [
        # Charge 1: $300.00, fee $9.00
        {"id": "txn_01", "type": "charge", "amount": 30000, "fee": 900, "currency": "usd", "source": "ch_01"},
        # Charge 2: $250.00, fee $7.50
        {"id": "txn_02", "type": "charge", "amount": 25000, "fee": 750, "currency": "usd", "source": "ch_02"},
        # Refund for Charge 1: $50.00, fee $3.50 refund fee adjustment
        {"id": "txn_03", "type": "refund", "amount": -5000, "fee": 350, "currency": "usd", "source": "ch_01"},
    ]
    # Gross: $300 + $250 = $550.00
    # Fees: $9.00 + $7.50 + $3.50 = $20.00
    # Refunds: $50.00
    # Net = $550 - $20 - $50 = $480.00 == Payout Amount!

    recon: StripePayoutReconciliation = StripeSettlementReconciler.reconcile_payout(payout, balance_txns)

    assert recon.is_reconciled is True
    assert recon.delta_net == Decimal("0.00")
    assert recon.gross_amount == Decimal("550.00")
    assert recon.fee_amount == Decimal("20.00")
    assert recon.refund_amount == Decimal("50.00")
    assert recon.calculated_net == Decimal("480.00")
    assert recon.payout_amount == Decimal("480.00")
    assert recon.refund_count == 1
    assert recon.transaction_count == 3
    assert len(recon.discrepancies) == 0
    assert recon.evidence_tier == StripeEvidenceTier.TIER3_PAYOUT_SETTLEMENT


def test_scenario_09_discrepancy_detection_on_net_mismatch():
    """Scenario 9 (Negative): Reconciler detects and flags net settlement amount mismatch."""
    payout = {
        "id": "po_disc_01",
        "amount": 50000,  # $500.00 expected by bank deposit
        "currency": "usd",
        "status": "paid",
    }

    # Transactions actually sum to $480.00 net
    balance_txns = [
        {"id": "txn_01", "type": "charge", "amount": 50000, "fee": 2000, "currency": "usd"},  # net 480
    ]

    recon = StripeSettlementReconciler.reconcile_payout(payout, balance_txns)
    assert recon.is_reconciled is False
    assert recon.delta_net == Decimal("20.00")
    assert any("Net settlement mismatch" in d for d in recon.discrepancies)


def test_scenario_10_currency_mismatch_detection():
    """Scenario 10: Currency mismatch between payout and transaction is flagged."""
    payout = {
        "id": "po_cur_01",
        "amount": 10000,
        "currency": "usd",
        "status": "paid",
    }

    balance_txns = [
        {"id": "txn_eur_01", "type": "charge", "amount": 10000, "fee": 0, "currency": "eur"},
    ]

    recon = StripeSettlementReconciler.reconcile_payout(payout, balance_txns)
    assert recon.is_reconciled is False
    assert any("Currency mismatch" in d for d in recon.discrepancies)


def test_payout_status_unsettled_rejection():
    """Payout status other than 'paid' (e.g. pending, failed) fails reconciliation."""
    payout = {
        "id": "po_pend_01",
        "amount": 10000,
        "currency": "usd",
        "status": "pending",  # In transit or pending
    }

    balance_txns = [
        {"id": "txn_01", "type": "charge", "amount": 10300, "fee": 300, "currency": "usd"},
    ]

    recon = StripeSettlementReconciler.reconcile_payout(payout, balance_txns)
    assert recon.is_reconciled is False
    assert any("Payout is not settled" in d for d in recon.discrepancies)


def test_scenario_07_refund_linkage_to_charge():
    """Scenario 7: Subsequent refund is correctly linked to its originating charge."""
    balance_txns = [
        {"id": "txn_ch_01", "type": "charge", "amount": 10000, "source": "ch_parent_123"},
        {"id": "txn_rf_01", "type": "refund", "amount": -3000, "source": "ch_parent_123"},
        {"id": "txn_rf_02", "type": "refund", "amount": -2000, "source": "ch_parent_123"},
        {"id": "txn_ch_02", "type": "charge", "amount": 5000, "source": "ch_other_456"},
    ]

    linked = StripeSettlementReconciler.link_refunds_to_charges(balance_txns)
    assert "ch_parent_123" in linked
    assert len(linked["ch_parent_123"]) == 2
    assert linked["ch_parent_123"][0]["id"] == "txn_rf_01"
    assert linked["ch_parent_123"][1]["id"] == "txn_rf_02"
    assert "ch_other_456" not in linked


def test_post_close_adjustment_detection_and_quarantine():
    """Detect refunds arriving after period close to prevent silent mutation of closed periods."""
    closed_period_end = datetime(2026, 10, 15, 23, 59, 59, tzinfo=UTC)

    charge_dates = {
        "ch_period_1": datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC),
    }

    # Refund created on October 25 (10 days after period close)
    refund_ts = int(datetime(2026, 10, 25, 14, 0, 0, tzinfo=UTC).timestamp())
    balance_txns = [
        {
            "id": "txn_rf_post_close",
            "type": "refund",
            "amount": -5000,
            "currency": "usd",
            "created": refund_ts,
            "source": "ch_period_1",
        }
    ]

    adjustments = StripeSettlementReconciler.detect_post_close_adjustments(
        closed_period_end=closed_period_end,
        balance_transactions=balance_txns,
        charge_creation_dates=charge_dates,
    )

    assert len(adjustments) == 1
    adj = adjustments[0]
    assert adj.original_charge_id == "ch_period_1"
    assert adj.refund_transaction_id == "txn_rf_post_close"
    assert adj.amount == Decimal("50.00")
    assert adj.closed_period_end == closed_period_end


def test_evidence_tier_classification_distinction():
    """Verify that Stripe payout settlement evidence is explicitly Tier 3 and not Tier 4."""
    payout = {
        "id": "po_evidence_01",
        "amount": 10000,
        "currency": "usd",
        "status": "paid",
        "arrival_date": int(time.time()),
    }
    txns = [{"id": "txn_01", "type": "charge", "amount": 10000, "fee": 0, "currency": "usd"}]

    recon = StripeSettlementReconciler.reconcile_payout(payout, txns)
    assert recon.evidence_tier == StripeEvidenceTier.TIER3_PAYOUT_SETTLEMENT
    assert recon.evidence_tier.value == "tier3_payout_settlement"

    # Stripe payout does NOT constitute Tier 4 merchant accounting close
    assert recon.evidence_tier != StripeEvidenceTier.TIER4_ACCOUNTING_CLOSE
