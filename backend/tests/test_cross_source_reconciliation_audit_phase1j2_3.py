"""
NEXUS Phase 1J.2.3 — Cross-Source Reconciliation and Centralized Tenant Policy Audit Suite.

Verifies:
1. Multiple payment attempts (failed attempt 1, succeeded attempt 2 reconciled cleanly).
2. Composite payments (multiple partial payments summing to order gross -> MATCHED).
3. Partial payments (unpaid residual balance -> PARTIALLY_MATCHED).
4. Partial refunds (refund reduced net balance -> PARTIALLY_MATCHED with explanation).
5. Multiple candidate matches (ambiguous match without order link -> CONFLICT left unresolved for human review).
6. Unmatched commercial orders and orphan gateway payments are retained (never dropped).
7. Currency mismatch conflict (USD order vs EUR payment -> CONFLICT with zero currency guessing).
8. Centralized tenant certification policy:
   - Default deny.
   - Synthetic & sandbox provenance prohibited from certifying real tenants.
   - Server-side enforcement without client parameter bypasses.
   - Apex Specialty Commerce remains strictly in DIAGNOSTIC_ONLY status.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.tenant import Business, Organization
from app.services.cross_source_reconciliation_service import (
    CrossSourceMatchStatus,
    CrossSourceReconciliationService,
)
from app.services.tenant_certification_policy import (
    CertificationEligibilityStatus,
    TenantCertificationPolicy,
)
from sqlalchemy.orm import Session


@pytest.fixture
def disposable_business(db_session: Session) -> Business:
    org_id = str(uuid4())
    org = Organization(id=org_id, name="Reconciliation Audit Org", slug=f"recon-slug-{org_id[:8]}")
    db_session.add(org)
    biz = Business(
        id=str(uuid4()),
        organization_id=org.id,
        name="Disposable Test Merchant",
        industry="Retail Commerce",
    )
    db_session.add(biz)
    db_session.commit()
    return biz


def test_multiple_payment_attempts_reconciliation(disposable_business: Business):
    """Multiple payment attempts: Attempt 1 failed, Attempt 2 succeeded."""
    order = {
        "id": "ord_multi_101",
        "name": "#101",
        "currency": "USD",
        "total_price": "100.00",
    }
    txns = [
        # Attempt 1: Failed
        {
            "id": "txn_fail_101",
            "source": "ch_fail_101",
            "type": "charge",
            "amount": 10000,
            "fee": 0,
            "net": 0,
            "currency": "usd",
            "status": "failed",
            "paid": False,
            "failure_message": "Card expired",
            "metadata": {"order_id": "ord_multi_101"},
        },
        # Attempt 2: Succeeded
        {
            "id": "txn_succ_101",
            "source": "ch_succ_101",
            "type": "charge",
            "amount": 10000,
            "fee": 320,
            "net": 9680,
            "currency": "usd",
            "status": "succeeded",
            "paid": True,
            "metadata": {"order_id": "ord_multi_101"},
        },
    ]

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id=disposable_business.id,
        period_start=datetime.now(UTC) - timedelta(days=1),
        period_end=datetime.now(UTC),
        shopify_orders=[order],
        stripe_transactions=txns,
    )

    assert len(report.matches) == 1
    m = report.matches[0]
    assert m.status == CrossSourceMatchStatus.MATCHED
    assert m.payment_gross_amount == Decimal("100.00")
    assert any("Card expired" in d for d in m.discrepancy_reasons)
    assert "Multiple payment attempts" in m.notes


def test_composite_payment_reconciliation(disposable_business: Business):
    """Composite payment: Gift card ($20) + credit card ($80) totaling $100 order -> MATCHED."""
    order = {
        "id": "ord_comp_202",
        "name": "#202",
        "currency": "USD",
        "total_price": "100.00",
    }
    txns = [
        {
            "id": "txn_comp_part1",
            "source": "ch_comp_part1",
            "amount": 2000,
            "fee": 60,
            "net": 1940,
            "currency": "usd",
            "metadata": {"order_id": "ord_comp_202"},
        },
        {
            "id": "txn_comp_part2",
            "source": "ch_comp_part2",
            "amount": 8000,
            "fee": 260,
            "net": 7740,
            "currency": "usd",
            "metadata": {"order_id": "ord_comp_202"},
        },
    ]

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id=disposable_business.id,
        period_start=datetime.now(UTC) - timedelta(days=1),
        period_end=datetime.now(UTC),
        shopify_orders=[order],
        stripe_transactions=txns,
    )

    assert len(report.matches) == 1
    m = report.matches[0]
    assert m.status == CrossSourceMatchStatus.MATCHED
    assert m.payment_gross_amount == Decimal("100.00")
    assert m.variance_amount == Decimal("0.00")
    assert "Composite payment" in m.notes


def test_partial_payment_reconciliation(disposable_business: Business):
    """Partial payment: $150 order with only $100 captured -> PARTIALLY_MATCHED."""
    order = {
        "id": "ord_part_303",
        "name": "#303",
        "currency": "USD",
        "total_price": "150.00",
    }
    txns = [
        {
            "id": "txn_part_303",
            "source": "ch_part_303",
            "amount": 10000,
            "fee": 320,
            "net": 9680,
            "currency": "usd",
            "metadata": {"order_id": "ord_part_303"},
        }
    ]

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id=disposable_business.id,
        period_start=datetime.now(UTC) - timedelta(days=1),
        period_end=datetime.now(UTC),
        shopify_orders=[order],
        stripe_transactions=txns,
    )

    assert len(report.matches) == 1
    m = report.matches[0]
    assert m.status == CrossSourceMatchStatus.PARTIALLY_MATCHED
    assert m.variance_amount == Decimal("50.00")
    assert any("Partial payment" in d for d in m.discrepancy_reasons)


def test_partial_refund_subsequent_to_order(disposable_business: Business):
    """Order of $100 with subsequent refund of $25 -> PARTIALLY_MATCHED with refund details."""
    order = {
        "id": "ord_ref_404",
        "name": "#404",
        "currency": "USD",
        "total_price": "100.00",
    }
    txns = [
        {
            "id": "txn_ch_404",
            "source": "ch_404",
            "amount": 10000,
            "fee": 320,
            "net": 9680,
            "currency": "usd",
            "metadata": {"order_id": "ord_ref_404"},
        },
        {
            "id": "txn_refund_404",
            "type": "refund",
            "source": "ch_404",
            "amount": -2500,
            "fee": 0,
            "net": -2500,
            "currency": "usd",
        },
    ]

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id=disposable_business.id,
        period_start=datetime.now(UTC) - timedelta(days=1),
        period_end=datetime.now(UTC),
        shopify_orders=[order],
        stripe_transactions=txns,
    )

    assert len(report.matches) == 1
    m = report.matches[0]
    assert m.status == CrossSourceMatchStatus.PARTIALLY_MATCHED
    assert m.refund_amount == Decimal("25.00")
    assert any("subsequent refund of $25.00" in d for d in m.discrepancy_reasons)


def test_ambiguous_multiple_candidate_matches_unresolved(disposable_business: Business):
    """Multiple candidate transactions matching amount/currency without order reference must remain unresolved for human review."""
    # Order of $50.00 without gateway transaction IDs
    order = {
        "id": "ord_ambig_505",
        "name": "#505",
        "currency": "USD",
        "total_price": "50.00",
    }
    # Two identical $50.00 Stripe transactions on the same day without metadata!
    txns = [
        {
            "id": "txn_cand_alpha",
            "source": "ch_cand_alpha",
            "amount": 5000,
            "fee": 175,
            "net": 4825,
            "currency": "usd",
        },
        {
            "id": "txn_cand_beta",
            "source": "ch_cand_beta",
            "amount": 5000,
            "fee": 175,
            "net": 4825,
            "currency": "usd",
        },
    ]

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id=disposable_business.id,
        period_start=datetime.now(UTC) - timedelta(days=1),
        period_end=datetime.now(UTC),
        shopify_orders=[order],
        stripe_transactions=txns,
    )

    # Must flag the order as CONFLICT / ambiguous, leaving both candidates unclaimed
    order_matches = [m for m in report.matches if m.shopify_order_id == "ord_ambig_505"]
    assert len(order_matches) == 1
    om = order_matches[0]
    assert om.status == CrossSourceMatchStatus.CONFLICT
    assert om.match_strategy == "AMBIGUOUS_MULTIPLE_CANDIDATES"
    assert any("AMBIGUOUS_MATCH" in d for d in om.discrepancy_reasons)
    assert any("txn_cand_alpha" in d and "txn_cand_beta" in d for d in om.discrepancy_reasons)

    # Both candidate transactions must remain reported as UNMATCHED orphan payments for human review!
    orphan_matches = [m for m in report.matches if m.stripe_payment_id in ("txn_cand_alpha", "txn_cand_beta")]
    assert len(orphan_matches) == 2
    assert all(m.status == CrossSourceMatchStatus.UNMATCHED for m in orphan_matches)


def test_unmatched_orders_and_orphan_payments_retained(disposable_business: Business):
    """Unmatched commercial order and orphan gateway payment are preserved and surfaced."""
    # Order with no payment
    order = {"id": "ord_unmatched_01", "name": "#999", "currency": "USD", "total_price": "75.00"}
    # Payment with no order
    txn = {"id": "txn_orphan_01", "amount": 6000, "fee": 200, "net": 5800, "currency": "usd"}

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id=disposable_business.id,
        period_start=datetime.now(UTC) - timedelta(days=1),
        period_end=datetime.now(UTC),
        shopify_orders=[order],
        stripe_transactions=[txn],
    )

    assert report.is_fully_reconciled is False
    assert report.unmatched_orders_count == 1
    assert report.unmatched_payments_count == 1
    assert len(report.matches) == 2


def test_currency_mismatch_conflict(disposable_business: Business):
    """Currency mismatch (Order in USD, charge in EUR) is flagged as CONFLICT."""
    order = {"id": "ord_curr_01", "name": "#101", "currency": "USD", "total_price": "100.00"}
    txn = {
        "id": "txn_curr_01",
        "amount": 10000,
        "fee": 300,
        "net": 9700,
        "currency": "eur",
        "metadata": {"order_id": "ord_curr_01"},
    }

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id=disposable_business.id,
        period_start=datetime.now(UTC) - timedelta(days=1),
        period_end=datetime.now(UTC),
        shopify_orders=[order],
        stripe_transactions=[txn],
    )

    assert len(report.matches) == 1
    m = report.matches[0]
    assert m.status == CrossSourceMatchStatus.CONFLICT
    assert any("Currency mismatch" in d for d in m.discrepancy_reasons)


def test_centralized_tenant_certification_policy_apex_quarantine():
    """Verify centralized policy prevents real tenants (Apex) from certification via sandbox reconciliation."""
    apex_id = "ab044b1a-835a-4a38-bf45-62fe38624151"

    # 1. Policy check: Apex is recognized as real tenant
    assert TenantCertificationPolicy.is_real_tenant(apex_id) is True

    # 2. Evaluation with perfect math on sandbox data -> can_certify is strictly FALSE
    verdict = TenantCertificationPolicy.evaluate_certification_eligibility(
        business_id=apex_id,
        provenance="shopify_stripe_sandbox",
        is_sandbox=True,
        is_fully_reconciled=True,
    )
    assert verdict.can_certify is False
    assert verdict.status == CertificationEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code == "REAL_TENANT_SANDBOX_PROVENANCE_PROHIBITED"
    assert "GOVERNANCE VIOLATION PREVENTED" in verdict.explanation

    # 3. Assert throws PermissionError on attempted period close certification
    with pytest.raises(PermissionError, match="Governance Violation: Real tenant"):
        TenantCertificationPolicy.assert_can_certify_period_close(apex_id, "shopify_dev_store")
