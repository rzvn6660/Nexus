"""Intelligence and Insight Generation Engine for NEXUS Pulse (Section 10).

Translates calculated KPIs and period-over-period shifts into structured,
auditable management insights. Strictly categorizes outputs into:
- OBSERVED_FACT: Empirical reality directly recorded in the database.
- CALCULATED_KPI: Mathematical aggregations and period-over-period deltas.
- STATISTICAL_OBSERVATION: Distribution patterns, concentration, and dispersion.
- MODEL_INTERPRETATION: Machine-generated cadence and risk categorizations.
- RECOMMENDED_ACTION: Prescriptive management interventions requiring human approval.
"""

from uuid import uuid4

from app.schemas.pulse import (
    InsightSeverity,
    InsightType,
    KPICategory,
    PulseInsightItem,
    PulseKPIDefinition,
    PulseKPIPayload,
)


class PulseInsightEngine:
    """Synthesizes verified metrics into actionable executive intelligence."""

    @classmethod
    def generate_insights_and_summaries(
        cls,
        kpi_payload: PulseKPIPayload,
        business_name: str,
        period_label: str,
        report_url: str | None = None,
        watermark_status: str | None = None,
        is_synthetic: bool = False,
    ) -> tuple[list[PulseInsightItem], str, str]:
        """
        Generate structured insights, full executive narrative summary, and
        concise messaging summary formatted for WhatsApp and Telegram.
        """
        insights: list[PulseInsightItem] = []

        # 1. Financial & Revenue Insights
        fin = kpi_payload.financial
        tot_rev_kpi = fin.get("total_revenue")
        growth_kpi = fin.get("revenue_growth")
        aov_kpi = fin.get("average_order_value")
        orders_kpi = fin.get("total_orders")
        gross_margin_kpi = fin.get("gross_margin")

        curr_rev = tot_rev_kpi.value if tot_rev_kpi and isinstance(tot_rev_kpi.value, (int, float)) else 0.0
        growth_pct = growth_kpi.value if growth_kpi and isinstance(growth_kpi.value, (int, float)) else None
        orders_count = orders_kpi.value if orders_kpi and isinstance(orders_kpi.value, int) else 0
        aov_val = aov_kpi.value if aov_kpi and isinstance(aov_kpi.value, (int, float)) else None
        aov_suffix = f" with an average order value of ${aov_val:,.2f}" if aov_val else ""

        # Determine effective synthetic flag
        effective_synthetic = (
            is_synthetic
            or "sandbox" in business_name.lower()
            or "synthetic" in business_name.lower()
            or "demo" in business_name.lower()
            or watermark_status in ("DEMO_SYNTHETIC", "unverified_missing")
        )

        # Observed Fact: Revenue & Orders
        fact_title = "Sales Baseline (Stored Synthetic Records)" if effective_synthetic else "Commercial Sales Baseline (Stored Records)"
        fact_desc = (
            f"{business_name} recorded ${curr_rev:,.2f} in deterministically calculated sales from stored synthetic records across "
            f"{orders_count:,} completed orders{aov_suffix} during {period_label}."
            if effective_synthetic
            else f"{business_name} recorded ${curr_rev:,.2f} in calculated commercial sales across "
            f"{orders_count:,} completed orders{aov_suffix} during {period_label}."
        )
        insights.append(
            PulseInsightItem(
                insight_id=f"ins-fact-{uuid4().hex[:6]}",
                type=InsightType.OBSERVED_FACT,
                category=KPICategory.FINANCIAL,
                severity=InsightSeverity.INFO,
                title=fact_title,
                description=fact_desc,
                evidence_kpis=["total_revenue", "total_orders", "average_order_value"],
            )
        )

        # Calculated KPI: Revenue Delta
        if growth_pct is not None:
            direction = "expanded" if growth_pct >= 0 else "contracted"
            sev = InsightSeverity.POSITIVE if growth_pct >= 0 else InsightSeverity.WARNING
            insights.append(
                PulseInsightItem(
                    insight_id=f"ins-kpi-growth-{uuid4().hex[:6]}",
                    type=InsightType.CALCULATED_KPI,
                    category=KPICategory.FINANCIAL,
                    severity=sev,
                    title="Revenue Trajectory",
                    description=(
                        f"Commercial revenue {direction} by {growth_pct:+.1f}% compared to the prior baseline window "
                        f"(baseline: ${tot_rev_kpi.baseline_value:,.2f} vs current: ${curr_rev:,.2f})."
                    ),
                    evidence_kpis=["revenue_growth", "total_revenue"],
                )
            )

        # 2. Customer & Repeat Behavior Insights
        cust = kpi_payload.customer
        active_cust_kpi = cust.get("active_customers")
        repeat_rate_kpi = cust.get("repeat_purchase_rate")
        active_count = active_cust_kpi.value if active_cust_kpi and isinstance(active_cust_kpi.value, int) else 0
        repeat_rate = repeat_rate_kpi.value if repeat_rate_kpi and isinstance(repeat_rate_kpi.value, (int, float)) else 0.0

        # Divergence insight: Revenue growth vs Repeat rate decline
        if growth_pct is not None and growth_pct > 0 and repeat_rate < 40.0:
            insights.append(
                PulseInsightItem(
                    insight_id=f"ins-div-{uuid4().hex[:6]}",
                    type=InsightType.STATISTICAL_OBSERVATION,
                    category=KPICategory.CUSTOMER,
                    severity=InsightSeverity.WARNING,
                    title="Revenue Growth & Repeat Divergence",
                    description=(
                        f"While commercial revenue grew by {growth_pct:+.1f}%, active repeat purchase rate "
                        f"remained low at {repeat_rate:.1f}%. Growth is predominantly driven by customer acquisition "
                        "or larger basket sizes rather than repeat customer engagement."
                    ),
                    evidence_kpis=["revenue_growth", "repeat_purchase_rate", "active_customers"],
                    action_suggestion="Prioritize reorder reminders for first-time buyers approaching their second purchase window.",
                )
            )

        # 3. Churn Intelligence & Risk Distribution
        churn = kpi_payload.churn
        crit_kpi = churn.get("critical_risk_customers")
        high_kpi = churn.get("high_risk_customers")
        rev_risk_kpi = churn.get("revenue_at_risk")

        crit_count = crit_kpi.value if crit_kpi and isinstance(crit_kpi.value, int) else 0
        high_count = high_kpi.value if high_kpi and isinstance(high_kpi.value, int) else 0
        rev_at_risk = rev_risk_kpi.value if rev_risk_kpi and isinstance(rev_risk_kpi.value, (int, float)) else 0.0
        attention_total = crit_count + high_count

        if attention_total > 0:
            insights.append(
                PulseInsightItem(
                    insight_id=f"ins-churn-risk-{uuid4().hex[:6]}",
                    type=InsightType.MODEL_INTERPRETATION,
                    category=KPICategory.CHURN,
                    severity=InsightSeverity.CRITICAL if crit_count > 5 else InsightSeverity.WARNING,
                    title="Customer Cadence Deceleration",
                    description=(
                        f"A cohort of {attention_total:,} repeat buyers ({crit_count:,} critical, {high_count:,} high risk) "
                        f"have exceeded 2.0x their empirical inter-purchase baseline. Estimated historical spend exposure "
                        f"is ${rev_at_risk:,.2f}."
                    ),
                    evidence_kpis=["critical_risk_customers", "high_risk_customers", "revenue_at_risk"],
                    action_suggestion="Review pending retention actions in NEXUS to initiate human-approved outreach.",
                )
            )

        # 4. Retention Governance & Approval Pace
        ret = kpi_payload.retention
        pending_kpi = ret.get("retention_actions_pending")
        approved_kpi = ret.get("retention_actions_approved")
        lift_kpi = ret.get("retention_lift_pct_points")

        pending_recs = pending_kpi.value if pending_kpi and isinstance(pending_kpi.value, int) else 0
        approved_recs = approved_kpi.value if approved_kpi and isinstance(approved_kpi.value, int) else 0
        ret_lift = lift_kpi.value if lift_kpi and isinstance(lift_kpi.value, (int, float)) else 0.0

        if pending_recs > approved_recs:
            insights.append(
                PulseInsightItem(
                    insight_id=f"ins-ret-pace-{uuid4().hex[:6]}",
                    type=InsightType.RECOMMENDED_ACTION,
                    category=KPICategory.RETENTION,
                    severity=InsightSeverity.WARNING,
                    title="Retention Proposal Review Backlog",
                    description=(
                        f"{pending_recs:,} prescriptive retention proposals are currently awaiting merchant review, "
                        f"exceeding approved decisions ({approved_recs:,}). Automated execution is blocked; merchant "
                        "sign-off is required to activate high-urgency interventions."
                    ),
                    evidence_kpis=["retention_actions_pending", "retention_actions_approved"],
                    action_suggestion="Access the Retention Workspace to approve or decline pending customer proposals.",
                )
            )

        # 5. Product Concentration & Catalog Risk
        prod = kpi_payload.product
        conc_kpi = prod.get("top_product_concentration")
        top_sku_kpi = prod.get("top_selling_sku")
        conc_pct = conc_kpi.value if conc_kpi and isinstance(conc_kpi.value, (int, float)) else 0.0

        if conc_pct >= 50.0:
            insights.append(
                PulseInsightItem(
                    insight_id=f"ins-prod-conc-{uuid4().hex[:6]}",
                    type=InsightType.STATISTICAL_OBSERVATION,
                    category=KPICategory.PRODUCT,
                    severity=InsightSeverity.INFO,
                    title="Product Catalog Concentration",
                    description=(
                        f"The top 3 revenue-generating SKUs account for {conc_pct:.1f}% of total merchandise sales. "
                        f"Lead product: {top_sku_kpi.formatted_value if top_sku_kpi else 'Top SKU'}. Business performance "
                        "is significantly tied to inventory availability for these core lines."
                    ),
                    evidence_kpis=["top_product_concentration", "top_selling_sku"],
                )
            )

        # 6. Operational Watermark & Data Freshness
        ops = kpi_payload.operational
        wm_status_kpi = ops.get("watermark_verification_status")
        fresh_kpi = ops.get("data_freshness_hours")
        wm_status = str(wm_status_kpi.value) if wm_status_kpi else "verified_complete"
        fresh_hrs = fresh_kpi.value if fresh_kpi and isinstance(fresh_kpi.value, (int, float)) else 0.0

        if wm_status != "verified_complete":
            insights.append(
                PulseInsightItem(
                    insight_id=f"ins-ops-wm-{uuid4().hex[:6]}",
                    type=InsightType.OBSERVED_FACT,
                    category=KPICategory.OPERATIONAL,
                    severity=InsightSeverity.CRITICAL,
                    title="Data Completeness Notice",
                    description=(
                        f"Authoritative ingestion completeness status is '{wm_status}'. Recent commercial data may be "
                        "incomplete. Cadence risk metrics are restricted to diagnostic advisory only."
                    ),
                    evidence_kpis=["watermark_verification_status", "data_freshness_hours"],
                )
            )
        elif fresh_hrs > 24.0:
            insights.append(
                PulseInsightItem(
                    insight_id=f"ins-ops-fresh-{uuid4().hex[:6]}",
                    type=InsightType.OBSERVED_FACT,
                    category=KPICategory.OPERATIONAL,
                    severity=InsightSeverity.WARNING,
                    title="Data Pipeline Ingestion Latency",
                    description=(
                        f"Data pipeline sync latency is currently {fresh_hrs:.1f} hours from the last verified event."
                    ),
                    evidence_kpis=["data_freshness_hours"],
                )
            )

        # Build Full Executive Summary Narrative
        effective_wm_status = watermark_status or wm_status
        exec_summary = cls._compose_executive_summary(
            business_name=business_name,
            period_label=period_label,
            curr_rev=curr_rev,
            growth_pct=growth_pct,
            orders_count=orders_count,
            active_count=active_count,
            repeat_rate=repeat_rate,
            attention_total=attention_total,
            rev_at_risk=rev_at_risk,
            ret_lift=ret_lift,
            conc_pct=conc_pct,
            wm_status=effective_wm_status,
            gross_margin_kpi=gross_margin_kpi,
            is_synthetic=effective_synthetic,
        )

        # Build Concise Messaging Summary (WhatsApp / Telegram)
        msg_summary = cls._compose_messaging_summary(
            business_name=business_name,
            period_label=period_label,
            curr_rev=curr_rev,
            growth_pct=growth_pct,
            orders_count=orders_count,
            attention_total=attention_total,
            rev_at_risk=rev_at_risk,
            pending_recs=pending_recs,
            report_url=report_url,
        )

        return insights, exec_summary, msg_summary

    @classmethod
    def _compose_executive_summary(
        cls,
        business_name: str,
        period_label: str,
        curr_rev: float,
        growth_pct: float | None,
        orders_count: int,
        active_count: int,
        repeat_rate: float,
        attention_total: int,
        rev_at_risk: float,
        ret_lift: float,
        conc_pct: float,
        wm_status: str,
        gross_margin_kpi: PulseKPIDefinition | None = None,
        is_synthetic: bool = False,
    ) -> str:
        growth_str = (
            f"representing a {growth_pct:+.1f}% change compared to the preceding period"
            if growth_pct is not None
            else "with initial baseline tracking"
        )

        header_title = (
            f"**Executive Intelligence Overview — {business_name} ({period_label}) [Controlled Sandbox Validation]**"
            if is_synthetic
            else f"**Executive Intelligence Overview — {business_name} ({period_label})**"
        )

        if is_synthetic:
            p1 = (
                f"During the reporting period ({period_label}), {business_name} recorded ${curr_rev:,.2f} "
                f"in deterministically calculated sales from stored synthetic records across {orders_count:,} completed orders, "
                f"{growth_str}. Active customer engagement reached {active_count:,} accounts, with repeat buyers contributing "
                f"{repeat_rate:.1f}% of transacting accounts."
            )
        else:
            p1 = (
                f"During the reporting period ({period_label}), {business_name} recorded ${curr_rev:,.2f} "
                f"in calculated commercial sales across {orders_count:,} completed orders, {growth_str}. "
                f"Active customer engagement reached {active_count:,} accounts, with repeat buyers contributing "
                f"{repeat_rate:.1f}% of transacting accounts."
            )

        p2 = (
            f"From a retention risk perspective, NEXUS identified {attention_total:,} repeat buyers requiring management attention "
            f"(Critical and High urgency), representing approximately ${rev_at_risk:,.2f} in historical customer spend exposure. "
            "In non-contractual commerce, prolonged purchase gaps reflect cadence deceleration rather than permanent attrition; seasonal "
            "purchasing cycles and demand fluctuations should be evaluated."
        )

        # Gross margin methodology disclosure
        if gross_margin_kpi and gross_margin_kpi.value is not None:
            margin_val = gross_margin_kpi.value
            is_estimated = (
                "ESTIMATED" in str(gross_margin_kpi.formatted_value)
                or "catalog_average_markup" in str(gross_margin_kpi.limitations)
            )
            if is_estimated:
                p3 = (
                    f"Gross margin is estimated at {margin_val:.1f}% based on catalog-average-markup methodology. "
                    "Because individual transaction line items lack invoice-verified vendor costs, this figure represents "
                    "a modeled benchmark and must not be represented as actual audited accounting profitability."
                )
            else:
                p3 = (
                    f"Gross margin is {margin_val:.1f}%, derived from verified product unit costs across completed sale items."
                )
        else:
            p3 = "Gross margin is currently unavailable as unit cost data is unrecorded."

        # Provenance and source completeness disclosure
        is_unverified = (
            is_synthetic
            or wm_status != "verified_complete"
            or wm_status in ("DEMO_SYNTHETIC", "unverified_missing", "SOURCE_COMPLETENESS_UNVERIFIED", "INCOMPLETE_IN_FLIGHT")
        )
        if is_unverified:
            provenance_text = (
                f"Source completeness is UNVERIFIED (status: '{wm_status}'). While calculation validity from stored "
                "database records is confirmed, upstream source completeness has not been certified. Prescriptive retention "
                "proposals remain advisory only and subject to Human-in-the-Loop merchant review."
            )
        else:
            provenance_text = (
                f"Authoritative source completeness is certified under status '{wm_status}'. All prescriptive retention proposals "
                "remain subject to Human-in-the-Loop merchant review before external customer communications are dispatched."
            )

        p4 = f"Merchandise sales exhibited a {conc_pct:.1f}% concentration in the top three catalog SKUs. {provenance_text}"

        return "\n\n".join([header_title, p1, p2, p3, p4])

    @classmethod
    def _compose_messaging_summary(
        cls,
        business_name: str,
        period_label: str,
        curr_rev: float,
        growth_pct: float | None,
        orders_count: int,
        attention_total: int,
        rev_at_risk: float,
        pending_recs: int,
        report_url: str | None = None,
    ) -> str:
        """Compact, structured notification message formatted for WhatsApp and Telegram."""
        growth_badge = f" ({growth_pct:+.1f}%)" if growth_pct is not None else ""
        link_str = f"\n\n📊 *Full Executive Report:* {report_url}" if report_url else ""

        lines = [
            "📈 *NEXUS Pulse — Executive Update*",
            f"🏢 *{business_name}* | {period_label}",
            "────────────────────────",
            f"💰 *Revenue:* ${curr_rev:,.2f}{growth_badge}",
            f"📦 *Completed Orders:* {orders_count:,}",
            f"⚠️ *At-Risk Repeat Buyers:* {attention_total:,}",
            f"🛡️ *Spend Exposure:* ${rev_at_risk:,.2f}",
            f"⚡ *Pending Retention Reviews:* {pending_recs:,}",
            "────────────────────────",
            f"💡 *Action:* Review at-risk customer proposals in NEXUS workspace.{link_str}",
            "\n_Confidential management report. Observational intelligence only._",
        ]
        return "\n".join(lines)
