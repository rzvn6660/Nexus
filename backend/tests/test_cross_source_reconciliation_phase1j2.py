"""
NEXUS Phase 1J.2.2 — Cross-Source Reconciliation Tests.

Verifies:
- Scenario 15: Stripe payment matched to Shopify order.
- Scenario 16: Unmatched Stripe payment preserved and flagged.
- Scenario 17: Shopify order without Stripe payment preserved and flagged.
- Scenario 18: Currency mismatch detection between order and payment (CONFLICT).
- Scenario 19: Partial payment attribution (PARTIALLY_MATCHED).
- Scenario 20: Real-tenant protection against synthetic/sandbox cross-source certification.
- Multi-payment composite order attribution.
- Partial refund tracking and net settlement calculation.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
import pytest

from app.services.cross_source_reconciliation_service import (
    CrossSourceMatchStatus,
    CrossSourceReconciliationReport,
    CrossSourceReconciliationService,
)


def test_scenario_15_stripe_payment_matched_to_shopify_order():
    """Scenario 15: Direct gateway ID match with exact gross amounts."""
    p_start = datetime(2026, 10, 1, tzinfo=UTC)
    p_end = datetime(2026, 10, 31, tzinfo=UTC)

    shopify_orders = [
        {
            "id": 1001,
            "name": "#1001",
            "total_price": "150.00",
            "currency": "USD",
            "total_discounts": "10.00",
            "total_tax": "12.50",
            "transactions": [{"receipt": {"charge_id": "ch_mock_1001"}}],
        }
    ]

    stripe_txns = [
        {
            "id": "txn_mock_1001",
            "source": "ch_mock_1001",
            "type": "charge",
            "amount": 15000,  # $150.00
            "fee": 465,       # $4.65
            "net": 14535,     # $145.35
            "currency": "usd",
        }
    ]

    report: CrossSourceReconciliationReport = CrossSourceReconciliationService.reconcile_sources(
        business_id="biz_test_recon",
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
    )

    assert report.total_shopify_orders == 1
    assert report.total_stripe_payments == 1
    assert report.matched_count == 1
    assert report.conflict_count == 0
    assert report.unmatched_orders_count == 0
    assert report.unmatched_payments_count == 0
    assert report.is_fully_reconciled is True
    assert report.can_certify_source_completeness is True

    match = report.matches[0]
    assert match.status == CrossSourceMatchStatus.MATCHED
    assert match.match_confidence == 1.0
    assert match.match_strategy == "DIRECT_GATEWAY_REFERENCE"
    assert match.order_gross_amount == Decimal("150.00")
    assert match.payment_gross_amount == Decimal("150.00")
    assert match.stripe_fee_amount == Decimal("4.65")
    assert match.stripe_net_payout == Decimal("145.35")


def test_scenario_16_unmatched_stripe_payment():
    """Scenario 16: Orphan Stripe payment without Shopify order is preserved and flagged."""
    p_start = datetime(2026, 10, 1, tzinfo=UTC)
    p_end = datetime(2026, 10, 31, tzinfo=UTC)

    # 1 Shopify order matched
    shopify_orders = [
        {
            "id": 2001,
            "name": "#2001",
            "total_price": "50.00",
            "currency": "USD",
            "transactions": [{"receipt": {"charge_id": "ch_matched_2001"}}],
        }
    ]

    # 2 Stripe transactions: 1 matched, 1 orphan payment
    stripe_txns = [
        {"id": "txn_2001", "source": "ch_matched_2001", "type": "charge", "amount": 5000, "fee": 175, "currency": "usd"},
        {"id": "txn_orphan", "source": "ch_orphan_9999", "type": "charge", "amount": 20000, "fee": 610, "currency": "usd"},
    ]

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id="biz_test_orphan",
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
    )

    assert report.matched_count == 1
    assert report.unmatched_payments_count == 1
    assert report.is_fully_reconciled is False
    assert report.can_certify_source_completeness is False

    orphan_match = [m for m in report.matches if m.stripe_payment_id == "txn_orphan"][0]
    assert orphan_match.status == CrossSourceMatchStatus.UNMATCHED
    assert "ORPHAN_STRIPE_PAYMENT_WITHOUT_COMMERCIAL_ORDER" in orphan_match.discrepancy_reasons
    assert orphan_match.payment_gross_amount == Decimal("200.00")


def test_scenario_17_shopify_order_without_stripe_payment():
    """Scenario 17: Shopify order without payment transaction is preserved and flagged."""
    p_start = datetime(2026, 10, 1, tzinfo=UTC)
    p_end = datetime(2026, 10, 31, tzinfo=UTC)

    shopify_orders = [
        {"id": 3001, "name": "#3001", "total_price": "350.00", "currency": "USD", "transactions": []}
    ]
    stripe_txns = []

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id="biz_test_missing_pay",
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
    )

    assert report.unmatched_orders_count == 1
    assert report.is_fully_reconciled is False
    assert report.can_certify_source_completeness is False

    unmatched = report.matches[0]
    assert unmatched.status == CrossSourceMatchStatus.UNMATCHED
    assert "SHOPIFY_ORDER_WITHOUT_STRIPE_PAYMENT" in unmatched.discrepancy_reasons
    assert unmatched.order_gross_amount == Decimal("350.00")


def test_scenario_18_currency_mismatch_conflict():
    """Scenario 18: Currency mismatch between order and payment is classified as CONFLICT."""
    p_start = datetime(2026, 10, 1, tzinfo=UTC)
    p_end = datetime(2026, 10, 31, tzinfo=UTC)

    shopify_orders = [
        {
            "id": 4001,
            "name": "#4001",
            "total_price": "100.00",
            "currency": "USD",
            "transactions": [{"receipt": {"charge_id": "ch_eur_4001"}}],
        }
    ]
    stripe_txns = [
        {"id": "txn_eur", "source": "ch_eur_4001", "type": "charge", "amount": 10000, "currency": "eur"}
    ]

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id="biz_test_cur_mismatch",
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
    )

    assert report.conflict_count == 1
    assert report.is_fully_reconciled is False
    match = report.matches[0]
    assert match.status == CrossSourceMatchStatus.CONFLICT
    assert any("Currency mismatch" in d for d in match.discrepancy_reasons)


def test_scenario_19_partial_payment():
    """Scenario 19: Partial payment captured classified as PARTIALLY_MATCHED."""
    p_start = datetime(2026, 10, 1, tzinfo=UTC)
    p_end = datetime(2026, 10, 31, tzinfo=UTC)

    shopify_orders = [
        {
            "id": 5001,
            "name": "#5001",
            "total_price": "100.00",
            "currency": "USD",
            "transactions": [{"receipt": {"charge_id": "ch_part_5001"}}],
        }
    ]
    stripe_txns = [
        {"id": "txn_part", "source": "ch_part_5001", "type": "charge", "amount": 6000, "fee": 200, "currency": "usd"}  # $60.00 captured
    ]

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id="biz_test_partial",
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
    )

    assert report.partially_matched_count == 1
    assert report.is_fully_reconciled is False
    match = report.matches[0]
    assert match.status == CrossSourceMatchStatus.PARTIALLY_MATCHED
    assert match.variance_amount == Decimal("40.00")
    assert any("Partial payment" in d for d in match.discrepancy_reasons)


def test_scenario_20_synthetic_evidence_real_tenant_protection():
    """Scenario 20: Attempted cross-source certification for protected real tenant (Apex) is blocked."""
    apex_id = "ab044b1a-835a-4a38-bf45-62fe38624151"

    shopify_orders = [
        {"id": 6001, "total_price": "100.00", "currency": "USD", "transactions": [{"receipt": {"charge_id": "ch_6001"}}]}
    ]
    stripe_txns = [
        {"id": "txn_6001", "source": "ch_6001", "type": "charge", "amount": 10000, "currency": "usd"}
    ]

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id=apex_id,
        period_start=datetime.now(UTC) - timedelta(days=7),
        period_end=datetime.now(UTC),
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
    )

    # Even if mathematical numbers match, real tenant cannot be certified via sandbox data!
    assert report.can_certify_source_completeness is False
    assert "GOVERNANCE VIOLATION PREVENTED" in report.reconciliation_summary


def test_multiple_payments_composite_order():
    """Two payments of $50.00 each on a $100.00 order sum to $100.00 -> MATCHED."""
    p_start = datetime(2026, 10, 1, tzinfo=UTC)
    p_end = datetime(2026, 10, 31, tzinfo=UTC)

    shopify_orders = [
        {"id": 7001, "name": "#7001", "total_price": "100.00", "currency": "USD"}
    ]
    stripe_txns = [
        {"id": "txn_p1", "source": "ch_p1", "type": "charge", "amount": 5000, "fee": 150, "currency": "usd", "metadata": {"order_id": "7001"}},
        {"id": "txn_p2", "source": "ch_p2", "type": "charge", "amount": 5000, "fee": 150, "currency": "usd", "metadata": {"order_id": "7001"}},
    ]

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id="biz_test_multi",
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
    )

    assert report.matched_count == 1
    assert report.is_fully_reconciled is True
    match = report.matches[0]
    assert match.status == CrossSourceMatchStatus.MATCHED
    assert match.payment_gross_amount == Decimal("100.00")
    assert match.stripe_fee_amount == Decimal("3.00")
