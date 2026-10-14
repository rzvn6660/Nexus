"""Structured, reviewable explanation generator for prescriptive recommendations."""

from app.analytics.prescriptive.schemas import (
    PrescriptiveRecommendation,
    RecommendationStatus,
)


class PrescriptiveExplainer:
    """
    Constructs transparent, evidence-backed narrative reports for prescriptive recommendations.
    
    Guarantees:
    1. Strict structural separation between observed historical facts, prospective forecasts,
       explicit assumptions, and projected outcomes.
    2. Transparent alternatives evaluation matrix detailing trade-offs and constraint feasibility.
    3. Prominent abstention disclosures when evidence is insufficient or constraints conflict.
    4. Mandatory Human-in-the-Loop authorization banner barring autonomous execution.
    """

    @classmethod
    def explain(cls, recommendation: PrescriptiveRecommendation) -> str:
        """Render a complete, human-reviewable Markdown briefing from a prescriptive recommendation."""
        sections: list[str] = []

        # 1. Header & Executive Summary
        rec = recommendation
        header = f"# Prescriptive Recommendation: {rec.recommendation_id}\n"
        header += f"- **Category**: {rec.category.replace('_', ' ').title()}\n"
        header += f"- **Target Entity**: {rec.entity_type.title()} `{rec.entity_id or 'Global'}`\n"
        header += f"- **Governing Objective**: `{rec.objective.value}`\n"
        header += f"- **Status**: `{rec.status.value.upper()}`\n"
        header += f"- **Generated At**: {rec.created_at}"
        sections.append(header)

        # 2. Status & Abstention Rationale
        if rec.status != RecommendationStatus.ACTIONABLE:
            abstention_block = "## Status Advisory: Action Barred\n"
            if rec.status == RecommendationStatus.INSUFFICIENT_EVIDENCE:
                abstention_block += (
                    "> **INSUFFICIENT EVIDENCE**: The recommendation engine has abstained from prescribing "
                    "commercial actions due to inadequate data telemetry.\n>\n"
                    f"> **Detail**: {rec.abstention_reason or 'Underlying historical or forecast data is insufficient.'}"
                )
            elif rec.status == RecommendationStatus.CONFLICTING_CONSTRAINTS:
                abstention_block += (
                    "> **CONFLICTING CONSTRAINTS**: The specified business boundaries cannot be mutually satisfied.\n>\n"
                    f"> **Detail**: {rec.abstention_reason or 'Operational constraints violate financial or supplier ceilings.'}"
                )
            else:
                abstention_block += f"> **ABSTAINED**: {rec.abstention_reason or 'Recommendation criteria not met.'}"
            sections.append(abstention_block)

        # 3. Recommended Primary Action (if actionable)
        if rec.recommended_action and rec.status == RecommendationStatus.ACTIONABLE:
            action = rec.recommended_action
            action_block = "## Recommended Action (Optimal Feasible Candidate)\n"
            action_block += f"### {action.title}\n"
            action_block += f"{action.description}\n\n"
            action_block += "#### Quantified Impact Summary\n"
            action_block += (
                f"- **Immediate Working Capital Required**: ${action.impact.expected_cost:,.2f}\n"
                f"- **Projected Net Margin Delta**: ${action.impact.expected_margin_impact:,.2f}\n"
                f"- **Projected Revenue Impact**: ${action.impact.expected_revenue_impact:,.2f}\n"
                f"- **Service Level Achieved**: {action.impact.service_level_achieved * 100:.1f}%\n"
                f"- **Residual Stockout Risk**: {action.impact.stockout_risk * 100:.1f}%\n"
                f"- **Annual Holding Cost**: ${action.impact.holding_cost_annual:,.2f}\n"
            )
            if action.uncertainty.worst_case_margin != 0.0 or action.uncertainty.best_case_margin != 0.0:
                action_block += (
                    f"- **Outcome Dispersion (Worst / Expected / Best)**: "
                    f"${action.uncertainty.worst_case_margin:,.2f} / "
                    f"${action.uncertainty.expected_margin:,.2f} / "
                    f"${action.uncertainty.best_case_margin:,.2f}\n"
                )
            if action.trade_offs:
                action_block += "\n#### Commercial Trade-offs\n"
                for trade in action.trade_offs:
                    action_block += f"- {trade}\n"
            sections.append(action_block)

        # 4. Evaluated Alternatives Comparison Matrix
        if rec.alternatives:
            alt_block = "## Evaluated Alternatives Comparison\n"
            alt_block += "| Alternative | Feasible | Qty / % | Est. Cost | Est. Margin | Stockout Risk | Trade-offs |\n"
            alt_block += "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |\n"
            for alt in rec.alternatives:
                feas_str = "Yes" if alt.is_feasible else f"No ({', '.join(alt.constraint_violations)})"
                param_str = f"{alt.recommended_quantity} units" if alt.recommended_quantity > 0 else (
                    f"{alt.recommended_discount_pct * 100:.0f}% off" if alt.recommended_discount_pct > 0 else "0 units"
                )
                cost_str = f"${alt.impact.expected_cost:,.2f}"
                margin_str = f"${alt.impact.expected_margin_impact:,.2f}"
                risk_str = f"{alt.impact.stockout_risk * 100:.1f}%"
                trade_brief = "; ".join(alt.trade_offs[:2]) if alt.trade_offs else "Standard operations"
                alt_block += f"| **{alt.title}** | {feas_str} | {param_str} | {cost_str} | {margin_str} | {risk_str} | {trade_brief} |\n"
            sections.append(alt_block)

        # 5. Observed Historical Facts (Ground Truth Evidence)
        facts_block = "## Observed Historical Evidence (Ground Truth)\n"
        if rec.observed_facts:
            facts_block += "| Metric | Observed Value | Source Table | Description |\n"
            facts_block += "| :--- | :--- | :--- | :--- |\n"
            for f in rec.observed_facts:
                val_str = f"${f.value:,.2f}" if isinstance(f.value, (float, int)) and "price" in f.metric or "cost" in f.metric else str(f.value)
                facts_block += f"| `{f.metric}` | **{val_str}** | `{f.source_table}` | {f.description} |\n"
        else:
            facts_block += "*No baseline database facts were retrieved.*\n"
        sections.append(facts_block)

        # 6. Prospective Forecast Telemetry
        if rec.forecast_inputs:
            fcst_block = "## Prospective Forecast Inputs (Phase 26 Telemetry)\n"
            fcst_block += "| Metric | Point Forecast | Prediction Interval (95%) | Model | Horizon |\n"
            fcst_block += "| :--- | :---: | :---: | :---: | :---: |\n"
            for fcst in rec.forecast_inputs:
                fcst_block += (
                    f"| `{fcst.metric}` | **{fcst.point_forecast:,.2f}** | "
                    f"[{fcst.lower_bound:,.2f} – {fcst.upper_bound:,.2f}] | "
                    f"`{fcst.model_name}` | {fcst.horizon_periods} ({fcst.frequency}) |\n"
                )
            sections.append(fcst_block)

        # 7. Explicit Assumptions
        assump_block = "## Key Operational & Economic Assumptions\n"
        if rec.assumptions:
            for a in rec.assumptions:
                assump_block += f"- {a}\n"
        else:
            assump_block += "- Deterministic stationary cost and lead time parameters applied.\n"
        sections.append(assump_block)

        # 8. Analytical Limitations & Exogenous Risks
        limit_block = "## Analytical Boundaries & Unobserved Risks\n"
        if rec.limitations:
            for lim in rec.limitations:
                limit_block += f"- {lim}\n"
        else:
            limit_block += "- Exogenous supplier disruptions, macroeconomic shocks, and price elasticity shifts remain unobserved.\n"
        sections.append(limit_block)

        # 9. Human-in-the-Loop Approval Gate (Inviolable Safeguard)
        approval_gate = (
            "## Human Authorization Review Gate\n"
            "> **MANDATORY HUMAN APPROVAL REQUIRED**\n>\n"
            "> This recommendation is strictly advisory and grounded in deterministic mathematical evaluation.\n"
            "> Autonomous execution of purchasing, pricing, or inventory actions is **PROHIBITED** by system policy.\n"
            "> A qualified business manager must review the proposed quantities, budget allocations, and trade-offs "
            "prior to entering orders or executing catalog changes."
        )
        sections.append(approval_gate)

        return "\n\n".join(sections)
