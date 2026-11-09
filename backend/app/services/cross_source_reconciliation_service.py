"""
NEXUS Phase 1J.2.2 — Cross-Source Reconciliation Service.

Compares and reconciles commercial storefront records (Shopify) with
payment gateway settlement records (Stripe).
Classifies records into:
- MATCHED
- PARTIALLY_MATCHED
- UNMATCHED
- CONFLICT
- PENDING_SOURCE_EVIDENCE

Enforces:
1. Strict non-discarding of unmatched records (preserves orphan payments and orders).
2. Explicit multi-attribute confidence scoring (direct gateway ID vs correlated metadata).
3. Non-assumptive completeness evaluation (Stripe settlement does not prove Shopify completeness).
4. Protected real-tenant quarantine (synthetic/sandbox data cannot certify real tenants).
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.services.tenant_certification_policy import TenantCertificationPolicy

logger = logging.getLogger(__name__)


class CrossSourceMatchStatus(str, Enum):
    """Classification of cross-source reconciliation matches."""
    MATCHED = "MATCHED"
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"
    UNMATCHED = "UNMATCHED"
    CONFLICT = "CONFLICT"
    PENDING_SOURCE_EVIDENCE = "PENDING_SOURCE_EVIDENCE"


class CrossSourceOrderMatch(BaseModel):
    """Detailed reconciliation result for an individual commercial order or payment."""
    match_id: str = Field(default_factory=lambda: str(uuid4()))
    shopify_order_id: str | None = None
    shopify_order_number: str | None = None
    stripe_payment_id: str | None = None
    stripe_charge_id: str | None = None
    status: CrossSourceMatchStatus
    match_confidence: float = Field(ge=0.0, le=1.0)
    match_strategy: str
    order_currency: str | None = None
    payment_currency: str | None = None
    order_gross_amount: Decimal | None = None
    payment_gross_amount: Decimal | None = None
    order_discount_amount: Decimal = Decimal("0.00")
    order_tax_amount: Decimal = Decimal("0.00")
    order_shipping_amount: Decimal = Decimal("0.00")
    stripe_fee_amount: Decimal = Decimal("0.00")
    stripe_net_payout: Decimal = Decimal("0.00")
    refund_amount: Decimal = Decimal("0.00")
    variance_amount: Decimal = Decimal("0.00")
    discrepancy_reasons: list[str] = Field(default_factory=list)
    notes: str = ""


class CrossSourceReconciliationReport(BaseModel):
    """Aggregate reconciliation report comparing commercial orders with payment gateway records."""
    reconciliation_id: str = Field(default_factory=lambda: str(uuid4()))
    business_id: str
    period_start: datetime
    period_end: datetime
    total_shopify_orders: int
    total_stripe_payments: int
    matched_count: int = 0
    partially_matched_count: int = 0
    unmatched_orders_count: int = 0
    unmatched_payments_count: int = 0
    conflict_count: int = 0
    total_shopify_gross: Decimal = Decimal("0.00")
    total_stripe_gross: Decimal = Decimal("0.00")
    total_stripe_fees: Decimal = Decimal("0.00")
    total_stripe_net: Decimal = Decimal("0.00")
    matches: list[CrossSourceOrderMatch] = Field(default_factory=list)
    is_fully_reconciled: bool = False
    can_certify_source_completeness: bool = False
    reconciliation_summary: str = ""
    reconciled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CrossSourceReconciliationService:
    """
    Independent cross-source reconciliation engine.
    Compares commercial storefront records (Shopify) with payment settlement records (Stripe).
    """

    @classmethod
    def reconcile_sources(
        cls,
        business_id: str,
        period_start: datetime,
        period_end: datetime,
        shopify_orders: list[dict[str, Any]],
        stripe_transactions: list[dict[str, Any]],
    ) -> CrossSourceReconciliationReport:
        """
        Execute full cross-source reconciliation between Shopify commercial orders and Stripe payments.
        """
        # 1. Index Stripe transactions
        # Keys to index:
        # - charge_id / source (e.g. ch_..., pi_...)
        # - order_id from metadata or description
        # - transaction_id (txn_...)
        stripe_by_source: dict[str, dict[str, Any]] = {}
        stripe_by_order_ref: dict[str, list[dict[str, Any]]] = {}
        all_stripe_ids: set[str] = set()

        # Track refunds separately
        stripe_refunds_by_charge: dict[str, list[dict[str, Any]]] = {}

        total_stripe_gross = Decimal("0.00")
        total_stripe_fees = Decimal("0.00")
        total_stripe_net = Decimal("0.00")

        for txn in stripe_transactions:
            tx_id = txn.get("id", "")
            source_id = txn.get("source") or tx_id
            tx_type = txn.get("type", "charge")
            all_stripe_ids.add(tx_id)

            amt_raw = txn.get("amount", 0)
            fee_raw = txn.get("fee", 0)
            net_raw = txn.get("net", amt_raw - fee_raw)

            amt_dec = (
                amt_raw if isinstance(amt_raw, Decimal)
                else Decimal(abs(amt_raw)) / Decimal(100)
            )
            fee_dec = (
                fee_raw if isinstance(fee_raw, Decimal)
                else Decimal(abs(fee_raw)) / Decimal(100)
            )
            net_dec = (
                net_raw if isinstance(net_raw, Decimal)
                else Decimal(net_raw) / Decimal(100)
            )

            total_stripe_fees += fee_dec

            if tx_type == "refund" or (isinstance(amt_raw, (int, float)) and amt_raw < 0):
                # Group refund by source charge
                ch_id = txn.get("source") or txn.get("charge") or ""
                stripe_refunds_by_charge.setdefault(ch_id, []).append(txn)
                total_stripe_net += net_dec
            else:
                total_stripe_gross += amt_dec
                total_stripe_net += net_dec

                if source_id:
                    stripe_by_source[source_id] = txn

                meta = txn.get("metadata") or {}
                order_ref = meta.get("order_id") or meta.get("order_number") or txn.get("description")
                if order_ref:
                    clean_ref = str(order_ref).strip()
                    stripe_by_order_ref.setdefault(clean_ref, []).append(txn)

        # 2. Reconcile each Shopify order
        matches: list[CrossSourceOrderMatch] = []
        claimed_stripe_tx_ids: set[str] = set()

        total_shopify_gross = Decimal("0.00")

        for order in shopify_orders:
            order_id = str(order.get("id", ""))
            order_num = str(order.get("name", "")).strip()
            gross_str = str(order.get("total_price", "0.00"))
            order_gross = Decimal(gross_str)
            total_shopify_gross += order_gross

            order_cur = str(order.get("currency", "USD")).upper()
            order_disc = Decimal(str(order.get("total_discounts", "0.00")))
            order_tax = Decimal(str(order.get("total_tax", "0.00")))
            order_ship = Decimal(str(order.get("total_shipping_price_set", {}).get("shop_money", {}).get("amount", "0.00") if isinstance(order.get("total_shipping_price_set"), dict) else "0.00"))

            # Look for Stripe matches
            matched_txns: list[dict[str, Any]] = []
            strategy = "UNMATCHED"
            confidence = 0.0

            # Strategy A: Direct gateway reference embedded in order transactions
            for tx in order.get("transactions", []):
                rcpt = tx.get("receipt") or {}
                ch_ref = rcpt.get("charge_id") or rcpt.get("id") or tx.get("authorization")
                if ch_ref and ch_ref in stripe_by_source:
                    matched_txns.append(stripe_by_source[ch_ref])
                    strategy = "DIRECT_GATEWAY_REFERENCE"
                    confidence = 1.0

            # Strategy B: Match by order ID in Stripe metadata
            if not matched_txns:
                if order_id in stripe_by_order_ref:
                    matched_txns.extend(stripe_by_order_ref[order_id])
                    strategy = "METADATA_ORDER_NUMBER"
                    confidence = 1.0
                elif order_num and order_num in stripe_by_order_ref:
                    matched_txns.extend(stripe_by_order_ref[order_num])
                    strategy = "METADATA_ORDER_NUMBER"
                    confidence = 0.95

            # Strategy C: Correlation heuristic (exact amount, currency, and date match)
            if not matched_txns:
                candidate_txns = []
                for txn in stripe_transactions:
                    tx_id = txn.get("id")
                    if tx_id in claimed_stripe_tx_ids or txn.get("type") == "refund":
                        continue
                    t_amt = Decimal(abs(txn.get("amount", 0))) / Decimal(100)
                    t_cur = str(txn.get("currency", "USD")).upper()
                    if t_amt == order_gross and t_cur == order_cur:
                        candidate_txns.append(txn)

                if len(candidate_txns) == 1:
                    matched_txns.append(candidate_txns[0])
                    strategy = "CORRELATION_HEURISTIC"
                    confidence = 0.80
                elif len(candidate_txns) > 1:
                    # AMBIGUOUS MATCH: Multiple candidate matches without explicit reference.
                    # Invariant: Ambiguous matches must remain unresolved for human review!
                    cand_ids = [c.get("id", "") for c in candidate_txns]
                    matches.append(
                        CrossSourceOrderMatch(
                            shopify_order_id=order_id,
                            shopify_order_number=order_num,
                            status=CrossSourceMatchStatus.CONFLICT,
                            match_confidence=0.50,
                            match_strategy="AMBIGUOUS_MULTIPLE_CANDIDATES",
                            order_currency=order_cur,
                            order_gross_amount=order_gross,
                            order_discount_amount=order_disc,
                            order_tax_amount=order_tax,
                            order_shipping_amount=order_ship,
                            discrepancy_reasons=[
                                (
                                    f"AMBIGUOUS_MATCH: {len(candidate_txns)} candidate Stripe transactions {cand_ids} "
                                    f"match amount (${order_gross}) and currency ({order_cur}) without order reference. "
                                    "Requires human review."
                                )
                            ],
                            notes="Ambiguous candidate matches detected. Left unresolved pending human review.",
                        )
                    )
                    continue

            # Evaluate matches for this order
            if not matched_txns:
                # Unmatched order
                matches.append(
                    CrossSourceOrderMatch(
                        shopify_order_id=order_id,
                        shopify_order_number=order_num,
                        status=CrossSourceMatchStatus.UNMATCHED,
                        match_confidence=0.0,
                        match_strategy="UNMATCHED",
                        order_currency=order_cur,
                        order_gross_amount=order_gross,
                        order_discount_amount=order_disc,
                        order_tax_amount=order_tax,
                        order_shipping_amount=order_ship,
                        discrepancy_reasons=["SHOPIFY_ORDER_WITHOUT_STRIPE_PAYMENT"],
                        notes="Commercial order has no corresponding payment transaction in Stripe.",
                    )
                )
            else:
                # Tally payments
                p_gross = Decimal("0.00")
                p_fees = Decimal("0.00")
                p_net = Decimal("0.00")
                p_refund = Decimal("0.00")
                p_cur = ""
                discrepancies: list[str] = []
                succeeded_attempts = 0
                failed_attempts = 0

                primary_txn = matched_txns[0]
                primary_id = primary_txn.get("id")
                primary_ch = primary_txn.get("source") or primary_id

                for txn in matched_txns:
                    t_id = txn.get("id")
                    claimed_stripe_tx_ids.add(t_id)

                    t_cur = str(txn.get("currency", "USD")).upper()
                    p_cur = t_cur
                    if t_cur != order_cur:
                        discrepancies.append(f"Currency mismatch: order {order_cur} != payment {t_cur}")

                    # Check for failed payment attempts
                    t_status = txn.get("status")
                    t_paid = txn.get("paid", True)
                    if t_status == "failed" or t_paid is False:
                        failed_attempts += 1
                        discrepancies.append(
                            f"Payment attempt '{t_id}' failed: {txn.get('failure_message', txn.get('outcome', {}).get('seller_message', 'declined'))}"
                        )
                        continue

                    succeeded_attempts += 1
                    t_amt = Decimal(abs(txn.get("amount", 0))) / Decimal(100)
                    t_fee = Decimal(abs(txn.get("fee", 0))) / Decimal(100)
                    t_net = Decimal(txn.get("net", txn.get("amount", 0) - txn.get("fee", 0))) / Decimal(100)

                    p_gross += t_amt
                    p_fees += t_fee
                    p_net += t_net

                    # Look for associated refunds
                    ch_source = txn.get("source") or t_id
                    if ch_source in stripe_refunds_by_charge:
                        for ref_txn in stripe_refunds_by_charge[ch_source]:
                            claimed_stripe_tx_ids.add(ref_txn.get("id"))
                            r_amt = Decimal(abs(ref_txn.get("amount", 0))) / Decimal(100)
                            p_refund += r_amt

                variance = order_gross - p_gross

                # Classify match status
                currency_mismatches = [d for d in discrepancies if "Currency mismatch" in d]
                if currency_mismatches:
                    status = CrossSourceMatchStatus.CONFLICT
                elif succeeded_attempts == 0 and failed_attempts > 0:
                    status = CrossSourceMatchStatus.CONFLICT
                    discrepancies.append("All payment attempts for order failed in payment gateway.")
                elif abs(variance) <= Decimal("0.01"):
                    if p_refund > Decimal("0.00"):
                        status = CrossSourceMatchStatus.PARTIALLY_MATCHED
                        discrepancies.append(f"Order has subsequent refund of ${p_refund:.2f}")
                    else:
                        status = CrossSourceMatchStatus.MATCHED
                elif p_gross < order_gross:
                    status = CrossSourceMatchStatus.PARTIALLY_MATCHED
                    discrepancies.append(f"Partial payment: captured ${p_gross:.2f} of ${order_gross:.2f} (unpaid=${variance:.2f})")
                else:
                    status = CrossSourceMatchStatus.CONFLICT
                    discrepancies.append(f"Overpayment conflict: captured ${p_gross:.2f} exceeds order ${order_gross:.2f}")

                notes = ""
                if succeeded_attempts > 1 and abs(variance) <= Decimal("0.01"):
                    notes = f"Composite payment: {succeeded_attempts} transactions reconciled totaling ${p_gross:.2f}."
                elif failed_attempts > 0 and succeeded_attempts > 0:
                    notes = f"Multiple payment attempts: {failed_attempts} failed, succeeded on attempt '{primary_id}'."

                matches.append(
                    CrossSourceOrderMatch(
                        shopify_order_id=order_id,
                        shopify_order_number=order_num,
                        stripe_payment_id=primary_id,
                        stripe_charge_id=primary_ch,
                        status=status,
                        match_confidence=confidence,
                        match_strategy=strategy,
                        order_currency=order_cur,
                        payment_currency=p_cur,
                        order_gross_amount=order_gross,
                        payment_gross_amount=p_gross,
                        order_discount_amount=order_disc,
                        order_tax_amount=order_tax,
                        order_shipping_amount=order_ship,
                        stripe_fee_amount=p_fees,
                        stripe_net_payout=p_net - p_refund,
                        refund_amount=p_refund,
                        variance_amount=variance,
                        discrepancy_reasons=discrepancies,
                        notes=notes,
                    )
                )

        # 3. Identify unclaimed orphan Stripe payments
        for txn in stripe_transactions:
            tx_id = txn.get("id")
            if tx_id not in claimed_stripe_tx_ids:
                tx_type = txn.get("type", "charge")
                if tx_type == "refund":
                    continue  # Unattached refund
                t_amt = Decimal(abs(txn.get("amount", 0))) / Decimal(100)
                t_fee = Decimal(abs(txn.get("fee", 0))) / Decimal(100)
                t_net = Decimal(txn.get("net", txn.get("amount", 0) - txn.get("fee", 0))) / Decimal(100)
                matches.append(
                    CrossSourceOrderMatch(
                        stripe_payment_id=tx_id,
                        stripe_charge_id=txn.get("source") or tx_id,
                        status=CrossSourceMatchStatus.UNMATCHED,
                        match_confidence=0.0,
                        match_strategy="UNMATCHED",
                        payment_currency=str(txn.get("currency", "USD")).upper(),
                        payment_gross_amount=t_amt,
                        stripe_fee_amount=t_fee,
                        stripe_net_payout=t_net,
                        discrepancy_reasons=["ORPHAN_STRIPE_PAYMENT_WITHOUT_COMMERCIAL_ORDER"],
                        notes="Payment received in Stripe gateway with no corresponding order in Shopify storefront.",
                    )
                )

        # 4. Tally totals
        matched_c = sum(1 for m in matches if m.status == CrossSourceMatchStatus.MATCHED)
        partial_c = sum(1 for m in matches if m.status == CrossSourceMatchStatus.PARTIALLY_MATCHED)
        unmatched_ord_c = sum(1 for m in matches if m.status == CrossSourceMatchStatus.UNMATCHED and m.shopify_order_id)
        unmatched_pay_c = sum(1 for m in matches if m.status == CrossSourceMatchStatus.UNMATCHED and m.stripe_payment_id)
        conflict_c = sum(1 for m in matches if m.status == CrossSourceMatchStatus.CONFLICT)

        is_fully_reconciled = (
            len(matches) > 0
            and partial_c == 0
            and unmatched_ord_c == 0
            and unmatched_pay_c == 0
            and conflict_c == 0
        )

        # Centralized certification policy evaluation
        policy = TenantCertificationPolicy.evaluate_certification_eligibility(
            business_id=business_id,
            provenance="shopify_stripe_sandbox",
            is_sandbox=True,
            is_fully_reconciled=is_fully_reconciled,
        )
        can_certify = policy.can_certify
        summary = (
            f"{policy.explanation} "
            f"Details: {matched_c} matched, {partial_c} partial, "
            f"{unmatched_ord_c} unmatched orders, {unmatched_pay_c} orphan payments, {conflict_c} conflicts."
        )

        return CrossSourceReconciliationReport(
            business_id=business_id,
            period_start=period_start,
            period_end=period_end,
            total_shopify_orders=len(shopify_orders),
            total_stripe_payments=len(stripe_transactions),
            matched_count=matched_c,
            partially_matched_count=partial_c,
            unmatched_orders_count=unmatched_ord_c,
            unmatched_payments_count=unmatched_pay_c,
            conflict_count=conflict_c,
            total_shopify_gross=total_shopify_gross,
            total_stripe_gross=total_stripe_gross,
            total_stripe_fees=total_stripe_fees,
            total_stripe_net=total_stripe_net,
            matches=matches,
            is_fully_reconciled=is_fully_reconciled,
            can_certify_source_completeness=can_certify,
            reconciliation_summary=summary,
        )
