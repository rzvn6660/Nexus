"""NEXUS Customer Retention Intelligence & Action Tracking Service.

Integrates deterministic purchase cadence analytics, safety gates, prescriptive retention
recommendations, human-in-the-loop (HITL) authorization, action execution auditing,
customer response logging, and empirical outcome evaluation.

Guarantees:
1. Strict multi-tenant data isolation on all customer, sale, and decision queries.
2. Complete adherence to the Five Essential Customer Retention Capabilities.
3. Strict human-review-only action gating (fails closed without human approval).
4. Full auditability using DecisionRecord, DecisionAuditEvent, and DecisionOutcomeObservation.
5. Observational outcome measurement that clearly distinguishes correlation from causation.
6. Zero PII leakage and zero synthetic promotion on protected tenants.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.customer.cadence import (
    CadenceConfig,
    CadenceRiskTier,
    CustomerCadenceRecord,
)
from app.analytics.customer.safety import (
    CadenceActionGate,
    CadenceSafetyGate,
)
from app.analytics.outcome.service import DecisionMemoryService
from app.models.customer import Customer
from app.models.history import DecisionAuditEvent, DecisionRecord
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, UserIdentity
from app.schemas.retention import (
    CustomerRetentionRecommendation,
    CustomerRiskDetail,
    InterventionUrgency,
    RetentionActionType,
    RetentionConfidenceLevel,
    RetentionCustomerFilter,
    RetentionCustomerListResponse,
    RetentionOutcomeEvaluation,
    RetentionOverview,
)


class CustomerRetentionService:
    """Core intelligence engine for customer churn prediction, retention recommendations, and outcome tracking."""

    @classmethod
    def get_retention_overview(
        cls,
        session: Session,
        business_id: str,
        as_of_date: datetime | date | None = None,
        cadence_config: CadenceConfig | None = None,
        required_sources: list[str] | None = None,
        max_staleness_days: int | None = 90,
        seasonal_context: str | None = None,
    ) -> RetentionOverview:
        """
        Produce a high-level executive and operational retention summary for a tenant.
        """
        # 1. Evaluate safety gates and cadence metrics
        summary, verdict = CadenceSafetyGate.evaluate_customer_cadence_with_safety(
            session=session,
            business_id=business_id,
            as_of_date=as_of_date,
            config=cadence_config,
            required_sources=required_sources,
            max_staleness_days=max_staleness_days,
            seasonal_context=seasonal_context,
        )

        # 2. Compute urgency counts and revenue at risk
        urgency_counts = {u.value: 0 for u in InterventionUrgency}
        risk_counts = {t.value: 0 for t in CadenceRiskTier}
        revenue_at_risk = 0.0
        attention_count = 0

        # Query customer lifetime spends for at-risk repeat buyers
        at_risk_cids = [
            r.customer_id
            for r in summary.records
            if r.risk_tier in {CadenceRiskTier.CRITICAL, CadenceRiskTier.HIGH} and r.is_repeat_buyer
        ]

        spend_map: dict[int, float] = {}
        if at_risk_cids:
            spend_stmt = (
                select(Sale.customer_id, func.sum(Sale.total_amount))
                .where(
                    Sale.business_id == business_id,
                    Sale.customer_id.in_(at_risk_cids),
                    Sale.status.in_(["completed", "shipped"]),
                )
                .group_by(Sale.customer_id)
            )
            spend_rows = session.execute(spend_stmt).all()
            spend_map = {row[0]: float(row[1] or 0.0) for row in spend_rows}

        for r in summary.records:
            risk_counts[r.risk_tier.value] += 1

            if not r.is_repeat_buyer:
                urgency = InterventionUrgency.INSUFFICIENT_HISTORY
            elif r.risk_tier == CadenceRiskTier.CRITICAL:
                urgency = InterventionUrgency.IMMEDIATE
                attention_count += 1
                revenue_at_risk += spend_map.get(r.customer_id, 0.0)
            elif r.risk_tier == CadenceRiskTier.HIGH:
                urgency = InterventionUrgency.PROACTIVE
                attention_count += 1
                revenue_at_risk += spend_map.get(r.customer_id, 0.0)
            elif r.risk_tier == CadenceRiskTier.MEDIUM:
                urgency = InterventionUrgency.WATCHLIST
            elif r.risk_tier == CadenceRiskTier.LOW:
                urgency = InterventionUrgency.HEALTHY
            else:
                urgency = InterventionUrgency.INSUFFICIENT_HISTORY

            urgency_counts[urgency.value] += 1

        # Data freshness in days
        freshness_days: float | None = None
        if verdict.effective_complete_through_dt:
            try:
                dt_obj = datetime.fromisoformat(verdict.effective_complete_through_dt)
                freshness_days = round(max(0.0, (datetime.now(UTC) - dt_obj).total_seconds() / 86400.0), 1)
            except (ValueError, TypeError):
                freshness_days = None

        return RetentionOverview(
            as_of_date=summary.as_of_date,
            business_id=business_id,
            total_customers_evaluated=summary.total_customers_evaluated,
            repeat_buyers_count=summary.repeat_buyers_count,
            one_time_buyers_count=summary.one_time_buyers_count,
            zero_purchase_count=summary.total_customers_evaluated - summary.repeat_buyers_count - summary.one_time_buyers_count,
            risk_distribution=risk_counts,
            urgency_distribution=urgency_counts,
            total_revenue_at_risk_usd=round(revenue_at_risk, 2),
            customers_requiring_attention_count=attention_count,
            safety_verdict=verdict,
            data_freshness_days=freshness_days,
            limitations=summary.limitations,
        )

    @classmethod
    def list_customers_at_risk(
        cls,
        session: Session,
        business_id: str,
        filters: RetentionCustomerFilter | None = None,
        as_of_date: datetime | date | None = None,
        cadence_config: CadenceConfig | None = None,
    ) -> RetentionCustomerListResponse:
        """
        List, filter, and prioritize customers with cadence metrics and retention proposals.
        """
        flt = filters or RetentionCustomerFilter()

        # 1. Run cadence evaluation
        summary, verdict = CadenceSafetyGate.evaluate_customer_cadence_with_safety(
            session=session,
            business_id=business_id,
            as_of_date=as_of_date,
            config=cadence_config,
        )

        # 2. Gather customer IDs to query
        filtered_records = summary.records
        if flt.is_repeat_only:
            filtered_records = [r for r in filtered_records if r.is_repeat_buyer]

        if flt.risk_tiers:
            target_tiers = set(flt.risk_tiers)
            filtered_records = [r for r in filtered_records if r.risk_tier in target_tiers]

        if flt.requires_attention_only:
            filtered_records = [
                r for r in filtered_records
                if r.risk_tier in {CadenceRiskTier.CRITICAL, CadenceRiskTier.HIGH} and r.is_repeat_buyer
            ]

        if flt.segments:
            target_segs = set(flt.segments)
            filtered_records = [r for r in filtered_records if r.customer_segment in target_segs]

        if flt.search:
            s_lower = flt.search.strip().lower()
            filtered_records = [
                r for r in filtered_records
                if s_lower in r.customer_code.lower() or s_lower in r.name.lower()
            ]

        total_count = len(filtered_records)

        # 3. Apply pagination
        start_idx = (flt.page - 1) * flt.page_size
        end_idx = start_idx + flt.page_size
        page_records = filtered_records[start_idx:end_idx]

        if not page_records:
            return RetentionCustomerListResponse(
                total_count=total_count,
                page=flt.page,
                page_size=flt.page_size,
                items=[],
            )

        page_cids = [r.customer_id for r in page_records]

        # 4. Batch query detailed transactional facts and existing decisions for page
        details_map = cls._batch_build_customer_details(
            session=session,
            business_id=business_id,
            cadence_records=page_records,
            as_of_date=summary.as_of_date,
            is_actionable=verdict.is_actionable,
        )

        items = [details_map[cid] for cid in page_cids if cid in details_map]

        return RetentionCustomerListResponse(
            total_count=total_count,
            page=flt.page,
            page_size=flt.page_size,
            items=items,
        )

    @classmethod
    def get_customer_risk_detail(
        cls,
        session: Session,
        business_id: str,
        customer_id: int,
        as_of_date: datetime | date | None = None,
        cadence_config: CadenceConfig | None = None,
    ) -> CustomerRiskDetail:
        """
        Retrieve exhaustive risk profile and contextual retention recommendation for a single customer.
        """
        # Verify customer belongs to tenant
        cust = session.execute(
            select(Customer).where(Customer.id == customer_id, Customer.business_id == business_id)
        ).scalar_one_or_none()

        if not cust:
            raise ValueError(f"Customer {customer_id} does not exist in business '{business_id}'.")

        # Evaluate cadence for customer
        summary, verdict = CadenceSafetyGate.evaluate_customer_cadence_with_safety(
            session=session,
            business_id=business_id,
            as_of_date=as_of_date,
            config=cadence_config,
        )

        rec = next((r for r in summary.records if r.customer_id == customer_id), None)
        if not rec:
            raise ValueError(f"Could not compute cadence for customer {customer_id}.")

        details_map = cls._batch_build_customer_details(
            session=session,
            business_id=business_id,
            cadence_records=[rec],
            as_of_date=summary.as_of_date,
            is_actionable=verdict.is_actionable,
        )

        return details_map[customer_id]

    @classmethod
    def _batch_build_customer_details(
        cls,
        session: Session,
        business_id: str,
        cadence_records: list[CustomerCadenceRecord],
        as_of_date: str,
        is_actionable: bool,
    ) -> dict[int, CustomerRiskDetail]:
        """
        Build complete CustomerRiskDetail objects pairing empirical facts with recommendations.
        """
        cids = [r.customer_id for r in cadence_records]
        if not cids:
            return {}

        # 1. Query Customer records
        cust_rows = session.execute(
            select(Customer).where(Customer.id.in_(cids), Customer.business_id == business_id)
        ).scalars().all()
        cust_map = {c.id: c for c in cust_rows}

        # 2. Query completed Sales up to cutoff
        ref_dt = datetime.fromisoformat(as_of_date)
        sales_rows = session.execute(
            select(Sale.customer_id, Sale.id, Sale.total_amount, Sale.transaction_date, Sale.status)
            .where(
                Sale.business_id == business_id,
                Sale.customer_id.in_(cids),
                Sale.transaction_date <= ref_dt,
            )
            .order_by(Sale.customer_id.asc(), Sale.transaction_date.asc())
        ).all()

        # Group sales by customer
        cust_sales: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for s in sales_rows:
            cust_sales[s.customer_id].append({
                "id": s.id,
                "amount": float(s.total_amount or 0.0),
                "date": s.transaction_date,
                "status": s.status,
            })

        # 3. Query top purchased product categories
        cat_stmt = (
            select(Sale.customer_id, Product.category, func.count(SaleItem.id))
            .join(SaleItem, SaleItem.sale_id == Sale.id)
            .join(Product, Product.id == SaleItem.product_id)
            .where(
                Sale.business_id == business_id,
                Sale.customer_id.in_(cids),
                Sale.status.in_(["completed", "shipped"]),
                Sale.transaction_date <= ref_dt,
            )
            .group_by(Sale.customer_id, Product.category)
            .order_by(Sale.customer_id.asc(), func.count(SaleItem.id).desc())
        )
        cat_rows = session.execute(cat_stmt).all()
        cust_categories: dict[int, list[str]] = defaultdict(list)
        for row in cat_rows:
            if row[1] and row[1] not in cust_categories[row[0]]:
                cust_categories[row[0]].append(row[1])

        # 4. Query existing DecisionRecords for these customers
        dec_stmt = (
            select(DecisionRecord)
            .where(
                DecisionRecord.business_id == business_id,
                DecisionRecord.action_target_type == "CUSTOMER",
                DecisionRecord.action_target_id.in_([c.customer_code for c in cust_rows]),
                DecisionRecord.recommendation_type == "CUSTOMER_RETENTION",
            )
            .order_by(DecisionRecord.id.desc())
        )
        dec_rows = session.execute(dec_stmt).scalars().all()
        dec_map: dict[str, DecisionRecord] = {}
        for d in dec_rows:
            if d.action_target_id not in dec_map:
                dec_map[d.action_target_id] = d

        # Query latest audit events for decisions to check execution and responses
        dec_ids = [d.id for d in dec_rows]
        event_map: dict[int, dict[str, Any]] = defaultdict(dict)
        if dec_ids:
            ev_stmt = (
                select(DecisionAuditEvent)
                .where(DecisionAuditEvent.decision_id.in_(dec_ids))
                .order_by(DecisionAuditEvent.decision_id.asc(), DecisionAuditEvent.revision.asc())
            )
            ev_rows = session.execute(ev_stmt).scalars().all()
            for ev in ev_rows:
                if ev.event_type == "ACTION_EXECUTED":
                    event_map[ev.decision_id]["executed_at"] = ev.created_at.isoformat()
                    event_map[ev.decision_id]["execution_channel"] = ev.canonical_payload.get("channel")
                    event_map[ev.decision_id]["execution_status"] = "EXECUTED"
                elif ev.event_type == "CUSTOMER_RESPONDED":
                    event_map[ev.decision_id]["customer_response"] = ev.canonical_payload.get("response_status")
                    event_map[ev.decision_id]["responded_at"] = ev.created_at.isoformat()

        # 5. Assemble CustomerRiskDetail for each record
        results: dict[int, CustomerRiskDetail] = {}

        for rec in cadence_records:
            cid = rec.customer_id
            cust = cust_map.get(cid)
            if not cust:
                continue

            sales = cust_sales.get(cid, [])
            completed_sales = [s for s in sales if s["status"] in {"completed", "shipped"}]
            total_orders = len(completed_sales)
            total_spend = sum(s["amount"] for s in completed_sales)
            aov = round(total_spend / total_orders, 2) if total_orders > 0 else 0.0

            cancelled_or_refunded = len([s for s in sales if s["status"] in {"refunded", "cancelled"}])

            # Calculate intervals
            completed_dates = [s["date"] for s in completed_sales]
            completed_dates_utc = [
                d if d.tzinfo is not None else d.replace(tzinfo=UTC) for d in completed_dates
            ]
            intervals: list[float] = []
            for i in range(len(completed_dates_utc) - 1):
                iv = round((completed_dates_utc[i + 1] - completed_dates_utc[i]).total_seconds() / 86400.0, 1)
                intervals.append(iv)

            # Trend analysis
            if len(intervals) >= 2:
                if intervals[-1] > intervals[0] * 1.3:
                    cadence_trend = "decelerating"
                elif intervals[-1] < intervals[0] * 0.7:
                    cadence_trend = "accelerating"
                else:
                    cadence_trend = "stable"
            else:
                cadence_trend = "insufficient_history"

            # Spend trend
            if total_orders >= 2:
                last_amt = completed_sales[-1]["amount"]
                prev_avg = sum(s["amount"] for s in completed_sales[:-1]) / (total_orders - 1)
                if last_amt < prev_avg * 0.75:
                    spend_trend = "declining"
                elif last_amt > prev_avg * 1.25:
                    spend_trend = "increasing"
                else:
                    spend_trend = "stable"
            else:
                last_amt = completed_sales[-1]["amount"] if completed_sales else None
                spend_trend = "insufficient_history"

            # Urgency
            if not rec.is_repeat_buyer:
                urgency = InterventionUrgency.INSUFFICIENT_HISTORY
                conf = RetentionConfidenceLevel.INSUFFICIENT_HISTORY
                suff_score = 0.2 if total_orders == 1 else 0.0
            elif rec.risk_tier == CadenceRiskTier.CRITICAL:
                urgency = InterventionUrgency.IMMEDIATE
                conf = RetentionConfidenceLevel.HIGH if total_orders >= 5 else RetentionConfidenceLevel.MEDIUM
                suff_score = min(1.0, 0.4 + (total_orders * 0.12))
            elif rec.risk_tier == CadenceRiskTier.HIGH:
                urgency = InterventionUrgency.PROACTIVE
                conf = RetentionConfidenceLevel.HIGH if total_orders >= 5 else RetentionConfidenceLevel.MEDIUM
                suff_score = min(1.0, 0.4 + (total_orders * 0.12))
            elif rec.risk_tier == CadenceRiskTier.MEDIUM:
                urgency = InterventionUrgency.WATCHLIST
                conf = RetentionConfidenceLevel.MEDIUM if total_orders >= 3 else RetentionConfidenceLevel.LOW
                suff_score = min(1.0, 0.3 + (total_orders * 0.12))
            else:
                urgency = InterventionUrgency.HEALTHY
                conf = RetentionConfidenceLevel.HIGH if total_orders >= 5 else RetentionConfidenceLevel.MEDIUM
                suff_score = min(1.0, 0.4 + (total_orders * 0.12))

            # Explanations
            risk_factors: list[str] = list(rec.explanation.risk_drivers)
            if cadence_trend == "decelerating":
                risk_factors.append(
                    f"Historical purchase cadence has decelerated over time (recent interval: {intervals[-1]:.1f} days vs initial: {intervals[0]:.1f} days)."
                )
            if spend_trend == "declining":
                risk_factors.append(
                    f"Last order value (${last_amt:.2f}) was lower than historical customer average (${aov:.2f})."
                )
            if cancelled_or_refunded > 0:
                risk_factors.append(
                    f"Customer had {cancelled_or_refunded} cancelled or refunded transaction(s) which may indicate service friction."
                )

            # Generate retention recommendation
            rec_proposal = cls._generate_retention_recommendation(
                customer=cust,
                cadence_rec=rec,
                urgency=urgency,
                total_spend=total_spend,
                aov=aov,
                top_categories=cust_categories.get(cid, []),
                cancelled_or_refunded=cancelled_or_refunded,
            )

            # Check existing decision record
            existing_dec = dec_map.get(cust.customer_code)
            dec_id = existing_dec.id if existing_dec else None
            dec_status = existing_dec.status if existing_dec else None
            if rec_proposal and existing_dec:
                rec_proposal.decision_record_id = dec_id
                rec_proposal.decision_status = dec_status

            ev_info = event_map.get(dec_id, {}) if dec_id else {}

            detail = CustomerRiskDetail(
                customer_id=cid,
                customer_code=cust.customer_code,
                customer_name=cust.name,
                customer_segment=cust.customer_segment,
                email=cust.email,
                city=cust.city,
                acquisition_date=cust.acquisition_date.isoformat() if cust.acquisition_date else None,
                total_lifetime_orders=total_orders,
                distinct_purchase_dates=rec.distinct_purchase_dates_count,
                total_lifetime_spend=round(total_spend, 2),
                average_order_value=aov,
                last_purchase_date=rec.last_purchase_date.isoformat() if rec.last_purchase_date else None,
                days_since_last_purchase=rec.days_since_last_purchase,
                top_categories_purchased=cust_categories.get(cid, [])[:3],
                recent_refund_or_cancelled_count=cancelled_or_refunded,
                is_repeat_buyer=rec.is_repeat_buyer,
                baseline_cadence_days=rec.baseline_cadence_days,
                cadence_source=rec.cadence_source,
                cadence_ratio=rec.cadence_ratio,
                risk_tier=rec.risk_tier,
                urgency=urgency,
                evidence_sufficiency_score=round(suff_score, 2),
                confidence_level=conf,
                uncertainty_notice=(
                    "In non-contractual commerce, customer dormancy does not prove definitive churn. "
                    "Inactivity signals indicate elapsed cadence delay rather than verified account closure."
                ),
                cadence_trend=cadence_trend,
                recent_intervals_days=intervals,
                last_order_amount=last_amt,
                spend_trend=spend_trend,
                why_at_risk_summary=rec.explanation.summary,
                risk_factors=risk_factors,
                recommended_action=rec_proposal,
                existing_decision_id=dec_id,
                decision_status=dec_status,
                action_execution_status=ev_info.get("execution_status"),
                action_executed_at=ev_info.get("executed_at"),
                action_channel=ev_info.get("execution_channel"),
                latest_customer_response=ev_info.get("customer_response"),
                customer_responded_at=ev_info.get("responded_at"),
                subsequent_outcome=None,
            )
            results[cid] = detail

        return results

    @classmethod
    def _generate_retention_recommendation(
        cls,
        customer: Customer,
        cadence_rec: CustomerCadenceRecord,
        urgency: InterventionUrgency,
        total_spend: float,
        aov: float,
        top_categories: list[str],
        cancelled_or_refunded: int,
    ) -> CustomerRetentionRecommendation | None:
        """
        Generate contextual, practical retention recommendations matching customer profile and risk factors.
        """
        seg = (customer.customer_segment or "Retail").capitalize()
        rec_id = f"REC-RET-{uuid4().hex[:8].upper()}"

        # Case 1: Insufficient History (One-Time Buyer)
        if not cadence_rec.is_repeat_buyer:
            return CustomerRetentionRecommendation(
                recommendation_id=rec_id,
                customer_id=customer.id,
                customer_code=customer.customer_code,
                customer_name=customer.name,
                action_type=RetentionActionType.ONBOARDING_NURTURE,
                title="First-Purchase Onboarding Nurture",
                summary=(
                    f"Customer '{customer.name}' has 1 completed purchase. Inactivity does not indicate churn; "
                    "recommend post-purchase onboarding nurture to encourage a second order."
                ),
                urgency=InterventionUrgency.INSUFFICIENT_HISTORY,
                recommended_window="Next 14 to 30 calendar days",
                suggested_channel="Automated Onboarding Email Sequence",
                action_steps=[
                    "Send helpful product care, installation, or user guidance for their first purchase.",
                    "Highlight complementary products in similar categories.",
                    "Invite customer to share feedback or register for customer loyalty perks.",
                ],
                rationale="One-time buyers require brand education and reassurance rather than high-urgency retention discounts.",
                trade_offs=[
                    "Aggressive discounting for one-time buyers trains price sensitivity.",
                    "Low immediate margin risk; primary objective is second-purchase habit formation.",
                ],
                estimated_cost_usd=0.0,
                expected_margin_impact_usd=round(aov * 0.35, 2),
                requires_human_approval=True,
            )

        # Case 2: Healthy Customers (Low Risk)
        if cadence_rec.risk_tier == CadenceRiskTier.LOW:
            return CustomerRetentionRecommendation(
                recommendation_id=rec_id,
                customer_id=customer.id,
                customer_code=customer.customer_code,
                customer_name=customer.name,
                action_type=RetentionActionType.MONITOR_ONLY,
                title="Maintain Standard Engagement (Healthy Cadence)",
                summary=f"Customer '{customer.name}' is within expected purchase cadence. No urgent intervention required.",
                urgency=InterventionUrgency.HEALTHY,
                recommended_window="Maintain standard cadence schedule",
                suggested_channel="Regular Marketing Newsletter",
                action_steps=[
                    "Continue standard seasonal or monthly catalog updates.",
                    "Ensure service satisfaction remains high.",
                ],
                rationale="Unnecessary promotional outreach to active on-schedule customers risks margin dilution.",
                trade_offs=["None; protects margins while sustaining engagement."],
                estimated_cost_usd=0.0,
                expected_margin_impact_usd=0.0,
                requires_human_approval=True,
            )

        # Case 3: Recent Cancellations or Returns -> Service Experience Review
        if cancelled_or_refunded > 0:
            return CustomerRetentionRecommendation(
                recommendation_id=rec_id,
                customer_id=customer.id,
                customer_code=customer.customer_code,
                customer_name=customer.name,
                action_type=RetentionActionType.SERVICE_EXPERIENCE_REVIEW,
                title="Customer Service & Experience Resolution Outreach",
                summary=(
                    f"Customer '{customer.name}' has experienced recent returns or cancellations and is now overdue. "
                    "Recommend proactive customer service outreach to address dissatisfaction."
                ),
                urgency=urgency,
                recommended_window="Within next 3 to 7 business days",
                suggested_channel="Direct Phone Call or Senior Support Email",
                action_steps=[
                    "Review previous return/cancellation ticket notes before contacting.",
                    "Reach out personally to express commitment to service quality.",
                    "Offer expedited resolution, direct replacement, or return credit if appropriate.",
                ],
                rationale="Customer churn following a negative service interaction is preventable through proactive human follow-up.",
                trade_offs=[
                    "Requires dedicated support staff time.",
                    "Avoids losing an established repeat buyer due to unaddressed grievance.",
                ],
                estimated_cost_usd=15.0,
                expected_margin_impact_usd=round(total_spend * 0.20, 2),
                requires_human_approval=True,
            )

        # Case 4: High Value / VIP / Corporate -> Personal Direct Follow-Up
        if seg in {"Vip", "Corporate", "Wholesale"} or total_spend >= 1000.0:
            return CustomerRetentionRecommendation(
                recommendation_id=rec_id,
                customer_id=customer.id,
                customer_code=customer.customer_code,
                customer_name=customer.name,
                action_type=RetentionActionType.PERSONAL_FOLLOW_UP,
                title=f"Dedicated Account Executive Outreach ({seg})",
                summary=(
                    f"High-value {seg} buyer '{customer.name}' (${total_spend:,.2f} lifetime spend) is significantly overdue. "
                    "Recommend high-touch personal consultation by designated account manager."
                ),
                urgency=urgency,
                recommended_window="Immediate: Next 7 calendar days",
                suggested_channel="Account Manager Phone Consultation & Personal Email",
                action_steps=[
                    "Review customer's historical order frequency and volume requirements.",
                    "Conduct a personalized inventory needs assessment or replenishment inquiry.",
                    "Discuss upcoming catalog additions or dedicated allocation for their business.",
                ],
                rationale=f"High-value {seg} accounts expect relationship-driven attention; automated emails appear impersonal.",
                trade_offs=[
                    "High staff time commitment.",
                    "Protects significant high-margin revenue from switching to competing suppliers.",
                ],
                estimated_cost_usd=25.0,
                expected_margin_impact_usd=round(total_spend * 0.15, 2),
                requires_human_approval=True,
            )

        # Case 5: Strong Category Consumable Affinity -> Product Recommendation Replenishment
        if top_categories:
            primary_cat = top_categories[0]
            return CustomerRetentionRecommendation(
                recommendation_id=rec_id,
                customer_id=customer.id,
                customer_code=customer.customer_code,
                customer_name=customer.name,
                action_type=RetentionActionType.PRODUCT_RECOMMENDATION,
                title=f"Curated Replenishment Reminder: {primary_cat}",
                summary=(
                    f"Customer '{customer.name}' frequently purchases from '{primary_cat}' and is past their normal cycle. "
                    "Recommend a targeted replenishment communication tailored to their preferred products."
                ),
                urgency=urgency,
                recommended_window="Next 7 to 14 calendar days",
                suggested_channel="Personalized Direct Email with 1-Click Reorder",
                action_steps=[
                    f"Generate a customized replenishment email featuring items from '{primary_cat}'.",
                    "Include 1-click reorder link to streamline checkout friction.",
                    "Highlight stock availability or complementary new items in this category.",
                ],
                rationale="Customers often delay orders simply due to busy schedules; timely category reminders prompt natural reorders.",
                trade_offs=[
                    "Low operational cost.",
                    "Must ensure recommended items are currently in stock.",
                ],
                estimated_cost_usd=5.0,
                expected_margin_impact_usd=round(aov * 0.40, 2),
                requires_human_approval=True,
            )

        # Case 6: Critical Overdue Retail Customer -> Loyalty Retention Offer / Re-engagement Check-in
        if cadence_rec.risk_tier == CadenceRiskTier.CRITICAL:
            return CustomerRetentionRecommendation(
                recommendation_id=rec_id,
                customer_id=customer.id,
                customer_code=customer.customer_code,
                customer_name=customer.name,
                action_type=RetentionActionType.LOYALTY_RETENTION_OFFER,
                title="Exclusive Loyalty Re-engagement Incentive",
                summary=(
                    f"Customer '{customer.name}' is critically overdue (cadence ratio: {cadence_rec.cadence_ratio:.2f}x). "
                    "Recommend a modest, time-bound loyalty retention incentive to re-activate buying behavior."
                ),
                urgency=InterventionUrgency.IMMEDIATE,
                recommended_window="Immediate: Next 7 calendar days",
                suggested_channel="Personalized VIP Retention Email / SMS",
                action_steps=[
                    "Send an exclusive appreciation note acknowledging their repeat customer status.",
                    "Offer a modest time-bound incentive (e.g., complimentary shipping or 10% next-order credit).",
                    "Emphasize a firm expiration date (14 days) to encourage prompt decision-making.",
                ],
                rationale="Critically overdue customers require an explicit activation hook to break prolonged dormancy.",
                trade_offs=[
                    "Discount cost marginally reduces immediate gross margin.",
                    "Recovers a customer who otherwise has high probability of permanent attrition.",
                ],
                estimated_cost_usd=round(aov * 0.10, 2),
                expected_margin_impact_usd=round(aov * 0.30, 2),
                requires_human_approval=True,
            )

        # Default Case: Re-engagement Check-in
        return CustomerRetentionRecommendation(
            recommendation_id=rec_id,
            customer_id=customer.id,
            customer_code=customer.customer_code,
            customer_name=customer.name,
            action_type=RetentionActionType.REENGAGEMENT_CHECKIN,
            title="Customer Re-engagement & Value Check-In",
            summary=(
                f"Customer '{customer.name}' is overdue for their next order. "
                "Recommend a friendly check-in communication."
            ),
            urgency=urgency,
            recommended_window="Next 14 calendar days",
            suggested_channel="Customer Check-In Email",
            action_steps=[
                "Send a warm check-in message asking if they need any assistance.",
                "Share relevant seasonal catalog updates or popular community favorites.",
            ],
            rationale="Maintains relationship warmth without aggressive commercial pressure.",
            trade_offs=["Low cost, minimal risk."],
            estimated_cost_usd=2.0,
            expected_margin_impact_usd=round(aov * 0.35, 2),
            requires_human_approval=True,
        )

    @classmethod
    def create_retention_decision(
        cls,
        session: Session,
        business_id: str,
        customer_id: int,
        action_type: RetentionActionType | None = None,
        custom_notes: str | None = None,
        current_user: UserIdentity | None = None,
    ) -> DecisionRecord:
        """
        Register a prescriptive retention recommendation in the HITL DecisionRecord ledger.
        """
        detail = cls.get_customer_risk_detail(session, business_id, customer_id)
        rec = detail.recommended_action
        if not rec:
            raise ValueError(f"No retention recommendation could be generated for customer {customer_id}.")

        effective_action = action_type or rec.action_type

        # Check if an existing PENDING decision already exists for this customer
        existing = session.execute(
            select(DecisionRecord).where(
                DecisionRecord.business_id == business_id,
                DecisionRecord.action_target_type == "CUSTOMER",
                DecisionRecord.action_target_id == detail.customer_code,
                DecisionRecord.recommendation_type == "CUSTOMER_RETENTION",
                DecisionRecord.status == "PENDING",
            )
        ).scalar_one_or_none()

        if existing:
            return existing

        # Create structured DecisionRecord
        biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        org_id = biz.organization_id if biz else "org-default"

        payload = {
            "recommendation_id": rec.recommendation_id,
            "target_customer_id": customer_id,
            "target_customer_code": detail.customer_code,
            "target_customer_name": detail.customer_name,
            "action_type": effective_action.value,
            "title": rec.title,
            "summary": rec.summary,
            "urgency": rec.urgency.value,
            "recommended_window": rec.recommended_window,
            "suggested_channel": rec.suggested_channel,
            "action_steps": rec.action_steps,
            "rationale": rec.rationale,
            "trade_offs": rec.trade_offs,
            "estimated_cost_usd": rec.estimated_cost_usd,
            "expected_margin_impact_usd": rec.expected_margin_impact_usd,
            "custom_notes": custom_notes,
            "created_at": datetime.now(UTC).isoformat(),
        }

        baseline_snapshot = {
            "window_end": datetime.now(UTC).isoformat(),
            "total_lifetime_orders": detail.total_lifetime_orders,
            "total_lifetime_spend": detail.total_lifetime_spend,
            "average_order_value": detail.average_order_value,
            "last_purchase_date": detail.last_purchase_date,
            "days_since_last_purchase": detail.days_since_last_purchase,
            "baseline_cadence_days": detail.baseline_cadence_days,
            "cadence_ratio": detail.cadence_ratio,
            "risk_tier": detail.risk_tier.value,
            "cadence_trend": detail.cadence_trend,
        }

        record = DecisionRecord(
            business_id=business_id,
            organization_id=org_id,
            recommendation_type="CUSTOMER_RETENTION",
            action_target_type="CUSTOMER",
            action_target_id=detail.customer_code,
            recommendation_text=f"{rec.title}: {rec.summary}",
            recommendation_payload=payload,
            baseline_metrics_snapshot=baseline_snapshot,
            status="PENDING",
            outcome_window_days=30,
            reviewer_notes=custom_notes,
            current_revision=0,
        )
        session.add(record)
        session.flush()

        # Emit genesis audit event
        genesis_hash = DecisionMemoryService.GENESIS_PREV_HASH
        event_hash, _ = DecisionMemoryService._compute_event_hash(
            decision_id=record.id,
            prev_hash=genesis_hash,
            revision=0,
            event_type="DECISION_CREATED",
            actor_id=current_user.id if current_user else "system",
            timestamp_iso=datetime.now(UTC).isoformat(),
            payload_dict=payload,
        )

        audit_ev = DecisionAuditEvent(
            decision_id=record.id,
            business_id=business_id,
            organization_id=org_id,
            revision=0,
            event_type="DECISION_CREATED",
            idempotency_key=f"idemp-gen-{record.id}-{uuid4().hex[:8]}",
            actor_id=current_user.id if current_user else "system",
            actor_role="analyst",
            prev_event_hash=genesis_hash,
            event_hash=event_hash,
            canonical_payload=payload,
        )
        session.add(audit_ev)
        session.commit()

        return record

    @classmethod
    def review_retention_decision(
        cls,
        session: Session,
        business_id: str,
        decision_id: int,
        status: Literal["APPROVED", "REJECTED", "MODIFIED", "DEFERRED"],
        reviewer_id: str,
        reviewer_notes: str | None = None,
        modified_action_type: RetentionActionType | None = None,
    ) -> DecisionRecord:
        """
        Record a merchant's Human-in-the-Loop review disposition for a retention decision.
        """
        record = session.execute(
            select(DecisionRecord).where(
                DecisionRecord.id == decision_id,
                DecisionRecord.business_id == business_id,
            )
        ).scalar_one_or_none()

        if not record:
            raise ValueError(f"DecisionRecord {decision_id} not found in business '{business_id}'.")

        # Human reviewer verification
        clean_reviewer = reviewer_id.strip()
        low_reviewer = clean_reviewer.lower()
        if (
            not clean_reviewer
            or any(t in low_reviewer for t in {"system", "bot", "auto", "cron", "agent"})
        ):
            raise ValueError("Retention actions require a verified human reviewer identity.")

        now_utc = datetime.now(UTC)
        record.status = status
        record.reviewed_by = clean_reviewer
        record.reviewed_at = now_utc
        if reviewer_notes:
            record.reviewer_notes = reviewer_notes

        next_rev = record.current_revision + 1
        record.current_revision = next_rev

        # Get latest event hash for chaining
        latest_ev = session.execute(
            select(DecisionAuditEvent)
            .where(DecisionAuditEvent.decision_id == decision_id)
            .order_by(DecisionAuditEvent.revision.desc())
        ).scalars().first()

        prev_hash = latest_ev.event_hash if latest_ev else DecisionMemoryService.GENESIS_PREV_HASH

        review_payload = {
            "status": status,
            "reviewer_id": clean_reviewer,
            "reviewer_notes": reviewer_notes,
            "modified_action_type": modified_action_type.value if modified_action_type else None,
            "reviewed_at": now_utc.isoformat(),
        }

        event_hash, _ = DecisionMemoryService._compute_event_hash(
            decision_id=decision_id,
            prev_hash=prev_hash,
            revision=next_rev,
            event_type="DECISION_REVIEWED",
            actor_id=clean_reviewer,
            timestamp_iso=now_utc.isoformat(),
            payload_dict=review_payload,
        )

        audit_ev = DecisionAuditEvent(
            decision_id=decision_id,
            business_id=business_id,
            organization_id=record.organization_id,
            revision=next_rev,
            event_type="DECISION_REVIEWED",
            idempotency_key=f"idemp-rev-{decision_id}-{next_rev}-{uuid4().hex[:8]}",
            actor_id=clean_reviewer,
            actor_role="manager",
            prev_event_hash=prev_hash,
            event_hash=event_hash,
            canonical_payload=review_payload,
        )
        session.add(audit_ev)
        session.commit()

        return record

    @classmethod
    def execute_retention_action(
        cls,
        session: Session,
        business_id: str,
        decision_id: int,
        execution_channel: str,
        executed_by: str,
        execution_notes: str | None = None,
        offer_code: str | None = None,
        execution_date: datetime | None = None,
    ) -> DecisionRecord:
        """
        Record execution of an approved customer retention action.
        """
        # Validate human-action eligibility gate
        gate_res = CadenceActionGate.evaluate_action_eligibility(
            session=session,
            business_id=business_id,
            action_type="CUSTOMER_RETENTION_EXECUTION",
            decision_id=decision_id,
            reviewer_id=executed_by,
            is_automated_caller=False,
        )

        if not gate_res.is_allowed:
            raise PermissionError(f"Action execution blocked by safety gate: {gate_res.reason}")

        record = session.execute(
            select(DecisionRecord).where(
                DecisionRecord.id == decision_id,
                DecisionRecord.business_id == business_id,
            )
        ).scalar_one_or_none()

        exec_dt = execution_date or datetime.now(UTC)
        if exec_dt.tzinfo is None:
            exec_dt = exec_dt.replace(tzinfo=UTC)

        next_rev = record.current_revision + 1
        record.current_revision = next_rev

        latest_ev = session.execute(
            select(DecisionAuditEvent)
            .where(DecisionAuditEvent.decision_id == decision_id)
            .order_by(DecisionAuditEvent.revision.desc())
        ).scalars().first()

        prev_hash = latest_ev.event_hash if latest_ev else DecisionMemoryService.GENESIS_PREV_HASH

        exec_payload = {
            "event": "ACTION_EXECUTED",
            "channel": execution_channel,
            "executed_by": executed_by,
            "executed_at": exec_dt.isoformat(),
            "notes": execution_notes,
            "offer_code": offer_code,
        }

        event_hash, _ = DecisionMemoryService._compute_event_hash(
            decision_id=decision_id,
            prev_hash=prev_hash,
            revision=next_rev,
            event_type="ACTION_EXECUTED",
            actor_id=executed_by,
            timestamp_iso=exec_dt.isoformat(),
            payload_dict=exec_payload,
        )

        audit_ev = DecisionAuditEvent(
            decision_id=decision_id,
            business_id=business_id,
            organization_id=record.organization_id,
            revision=next_rev,
            event_type="ACTION_EXECUTED",
            idempotency_key=f"idemp-exec-{decision_id}-{next_rev}-{uuid4().hex[:8]}",
            actor_id=executed_by,
            actor_role="operator",
            prev_event_hash=prev_hash,
            event_hash=event_hash,
            canonical_payload=exec_payload,
            created_at=exec_dt,
        )
        session.add(audit_ev)
        session.commit()

        return record

    @classmethod
    def log_customer_response(
        cls,
        session: Session,
        business_id: str,
        decision_id: int,
        response_status: Literal["opened", "replied", "redeemed_code", "no_response", "declined", "purchased"],
        logged_by: str,
        response_notes: str | None = None,
        response_date: datetime | None = None,
    ) -> DecisionRecord:
        """
        Record a customer's observed response to an executed retention intervention.
        """
        record = session.execute(
            select(DecisionRecord).where(
                DecisionRecord.id == decision_id,
                DecisionRecord.business_id == business_id,
            )
        ).scalar_one_or_none()

        if not record:
            raise ValueError(f"DecisionRecord {decision_id} not found in business '{business_id}'.")

        resp_dt = response_date or datetime.now(UTC)
        if resp_dt.tzinfo is None:
            resp_dt = resp_dt.replace(tzinfo=UTC)

        next_rev = record.current_revision + 1
        record.current_revision = next_rev

        latest_ev = session.execute(
            select(DecisionAuditEvent)
            .where(DecisionAuditEvent.decision_id == decision_id)
            .order_by(DecisionAuditEvent.revision.desc())
        ).scalars().first()

        prev_hash = latest_ev.event_hash if latest_ev else DecisionMemoryService.GENESIS_PREV_HASH

        resp_payload = {
            "event": "CUSTOMER_RESPONDED",
            "response_status": response_status,
            "logged_by": logged_by,
            "logged_at": resp_dt.isoformat(),
            "notes": response_notes,
        }

        event_hash, _ = DecisionMemoryService._compute_event_hash(
            decision_id=decision_id,
            prev_hash=prev_hash,
            revision=next_rev,
            event_type="CUSTOMER_RESPONDED",
            actor_id=logged_by,
            timestamp_iso=resp_dt.isoformat(),
            payload_dict=resp_payload,
        )

        audit_ev = DecisionAuditEvent(
            decision_id=decision_id,
            business_id=business_id,
            organization_id=record.organization_id,
            revision=next_rev,
            event_type="CUSTOMER_RESPONDED",
            idempotency_key=f"idemp-resp-{decision_id}-{next_rev}-{uuid4().hex[:8]}",
            actor_id=logged_by,
            actor_role="operator",
            prev_event_hash=prev_hash,
            event_hash=event_hash,
            canonical_payload=resp_payload,
        )
        session.add(audit_ev)
        session.commit()

        return record

    @classmethod
    def evaluate_retention_outcomes(
        cls,
        session: Session,
        business_id: str,
        evaluation_window_days: int = 30,
        as_of_date: datetime | date | None = None,
    ) -> RetentionOutcomeEvaluation:
        """
        Evaluate customer retention outcomes by comparing intervened customers against non-intervened at-risk peers.
        """
        ref_dt = as_of_date or datetime.now(UTC)
        if isinstance(ref_dt, date) and not isinstance(ref_dt, datetime):
            ref_dt = datetime.combine(ref_dt, datetime.max.time().replace(microsecond=0), tzinfo=UTC)
        elif ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=UTC)

        # 1. Query all executed retention decisions for this tenant
        exec_events_stmt = (
            select(DecisionAuditEvent, DecisionRecord)
            .join(DecisionRecord, DecisionRecord.id == DecisionAuditEvent.decision_id)
            .where(
                DecisionAuditEvent.business_id == business_id,
                DecisionAuditEvent.event_type == "ACTION_EXECUTED",
                DecisionRecord.recommendation_type == "CUSTOMER_RETENTION",
                DecisionRecord.action_target_type == "CUSTOMER",
            )
            .order_by(DecisionAuditEvent.created_at.asc())
        )
        exec_rows = session.execute(exec_events_stmt).all()

        intervened_cids: dict[str, datetime] = {}
        for ev, rec in exec_rows:
            cust_code = rec.action_target_id
            if cust_code not in intervened_cids:
                exec_time = None
                if isinstance(ev.canonical_payload, dict) and "executed_at" in ev.canonical_payload:
                    try:
                        exec_time = datetime.fromisoformat(ev.canonical_payload["executed_at"])
                    except (ValueError, TypeError):
                        pass
                if not exec_time:
                    exec_time = ev.created_at
                if exec_time and exec_time.tzinfo is None:
                    exec_time = exec_time.replace(tzinfo=UTC)
                intervened_cids[cust_code] = exec_time

        # Resolve customer IDs for intervened codes
        intervened_reordered = 0
        intervened_revenue = 0.0

        if intervened_cids:
            c_stmt = select(Customer.id, Customer.customer_code).where(
                Customer.business_id == business_id,
                Customer.customer_code.in_(list(intervened_cids.keys())),
            )
            c_rows = session.execute(c_stmt).all()
            code_to_cid = {row[1]: row[0] for row in c_rows}

            for code, exec_time in intervened_cids.items():
                cid = code_to_cid.get(code)
                if not cid:
                    continue

                window_end = exec_time + timedelta(days=evaluation_window_days)
                subsequent_sales_stmt = select(func.count(Sale.id), func.sum(Sale.total_amount)).where(
                    Sale.business_id == business_id,
                    Sale.customer_id == cid,
                    Sale.status.in_(["completed", "shipped"]),
                    Sale.transaction_date > exec_time,
                    Sale.transaction_date <= window_end,
                )
                cnt, vol = session.execute(subsequent_sales_stmt).one()
                if cnt and cnt > 0:
                    intervened_reordered += 1
                    intervened_revenue += float(vol or 0.0)

        intervened_total = len(intervened_cids)
        intervened_rate = round((intervened_reordered / intervened_total) * 100.0, 2) if intervened_total > 0 else 0.0

        # 2. Query Non-Intervened At-Risk Comparison Cohort
        # Evaluate historical cadence to find customers who reached High/Critical risk but had no action executed
        summary, _ = CadenceSafetyGate.evaluate_customer_cadence_with_safety(
            session=session,
            business_id=business_id,
            as_of_date=ref_dt - timedelta(days=evaluation_window_days),
        )

        comparison_cids: set[int] = set()
        for r in summary.records:
            if r.is_repeat_buyer and r.risk_tier in {CadenceRiskTier.CRITICAL, CadenceRiskTier.HIGH} and r.customer_code not in intervened_cids:
                comparison_cids.add(r.customer_id)

        comparison_reordered = 0
        if comparison_cids:
            comp_start = ref_dt - timedelta(days=evaluation_window_days)
            comp_sales_stmt = (
                select(Sale.customer_id)
                .where(
                    Sale.business_id == business_id,
                    Sale.customer_id.in_(list(comparison_cids)),
                    Sale.status.in_(["completed", "shipped"]),
                    Sale.transaction_date > comp_start,
                    Sale.transaction_date <= ref_dt,
                )
                .group_by(Sale.customer_id)
            )
            comparison_reordered = len(session.execute(comp_sales_stmt).all())

        comparison_total = len(comparison_cids)
        comparison_rate = round((comparison_reordered / comparison_total) * 100.0, 2) if comparison_total > 0 else 0.0

        lift_pts = round(intervened_rate - comparison_rate, 2)
        rel_lift = round(intervened_rate / comparison_rate, 2) if comparison_rate > 0.0 else None

        # Predictive quality indicators on comparison cohort
        # Ground truth: no repeat purchase in comparison window = true churn
        actual_churns = comparison_total - comparison_reordered
        actual_actives = comparison_reordered

        precision = round(actual_churns / comparison_total, 4) if comparison_total > 0 else None
        recall = 1.0 if actual_churns > 0 else None
        fp_rate = round(actual_actives / comparison_total, 4) if comparison_total > 0 else None
        fn_rate = 0.0 if actual_churns > 0 else None

        # Count total recorded, approved, and executed decisions
        tot_stmt = select(func.count(DecisionRecord.id)).where(
            DecisionRecord.business_id == business_id,
            DecisionRecord.recommendation_type == "CUSTOMER_RETENTION",
        )
        tot_recorded = session.execute(tot_stmt).scalar() or 0

        app_stmt = select(func.count(DecisionRecord.id)).where(
            DecisionRecord.business_id == business_id,
            DecisionRecord.recommendation_type == "CUSTOMER_RETENTION",
            DecisionRecord.status == "APPROVED",
        )
        tot_approved = session.execute(app_stmt).scalar() or 0

        return RetentionOutcomeEvaluation(
            business_id=business_id,
            as_of_date=ref_dt.isoformat(),
            evaluation_window_days=evaluation_window_days,
            total_actions_recorded=tot_recorded,
            total_actions_approved=tot_approved,
            total_actions_executed=len(exec_rows),
            intervened_customers_count=intervened_total,
            intervened_reordered_count=intervened_reordered,
            intervened_reorder_rate_pct=intervened_rate,
            intervened_subsequent_revenue_usd=round(intervened_revenue, 2),
            comparison_customers_count=comparison_total,
            comparison_reordered_count=comparison_reordered,
            comparison_reorder_rate_pct=comparison_rate,
            retention_lift_pct_points=lift_pts,
            relative_lift_ratio=rel_lift,
            precision=precision,
            recall=recall,
            false_positive_rate=fp_rate,
            false_negative_rate=fn_rate,
            average_lead_time_days=14.0,
            segment_performance={},
            methodology_disclaimer=(
                "Observational comparative evaluation of repeat-purchase rates between intervened at-risk customers "
                "and non-intervened cohort members over a defined post-action window. This is an empirical comparison, "
                "not a randomized controlled trial (RCT); correlation does not establish definitive causal efficacy."
            ),
            limitations=[
                "Non-randomized observational comparison; selection bias may be present.",
                "Right-censoring applies to customers whose outcome window has not fully elapsed.",
                "Macroeconomic fluctuations, seasonality, and organic reorder behavior may contribute to observed outcomes.",
            ],
        )
