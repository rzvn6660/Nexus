"""Hypothesis evaluation engine testing candidate explanations against empirical analytics results."""

from typing import Any

from app.investigation.models import (
    EvidenceLink,
    EvidenceStrength,
    HypothesisStatus,
    InvestigationHypothesis,
    InvestigationObservation,
)


class HypothesisEngine:
    """
    Evaluates candidate hypotheses systematically against deterministic tool execution outputs.
    Adheres strictly to evidence strength hierarchies without fabricated confidence probabilities.
    """

    @classmethod
    def evaluate_hypotheses(
        cls,
        hypotheses: list[InvestigationHypothesis],
        tool_results: list[dict[str, Any]],
        observations: list[InvestigationObservation],
    ) -> list[InvestigationHypothesis]:
        """Test and update every candidate hypothesis against collected empirical tool records."""
        updated: list[InvestigationHypothesis] = []

        # Index tool results by tool name for rapid inspection
        results_by_tool: dict[str, list[dict[str, Any]]] = {}
        for r in tool_results:
            t_name = r.get("tool", "")
            if t_name not in results_by_tool:
                results_by_tool[t_name] = []
            results_by_tool[t_name].append(r.get("result", {}))

        for hyp in hypotheses:
            h = hyp.model_copy(deep=True)
            cls._evaluate_single_hypothesis(h, results_by_tool, observations)
            updated.append(h)

        return updated

    @classmethod
    def _evaluate_single_hypothesis(
        cls,
        hyp: InvestigationHypothesis,
        results_by_tool: dict[str, list[dict[str, Any]]],
        observations: list[InvestigationObservation],
    ) -> None:
        """Route hypothesis to specialized empirical evaluation rule based on hypothesis type."""
        h_type = hyp.type

        if h_type in ("category_contribution", "category_variance"):
            cls._eval_category_variance(hyp, results_by_tool)
        elif h_type in ("volume_effect", "volume_driver", "volume_impact"):
            cls._eval_volume_effect(hyp, results_by_tool)
        elif h_type == "mix_effect":
            cls._eval_mix_effect(hyp, results_by_tool)
        elif h_type in ("price_effect", "cogs_impact"):
            cls._eval_price_or_cogs(hyp, results_by_tool)
        elif h_type == "stockout_constraint":
            cls._eval_stockout_constraint(hyp, results_by_tool)
        elif h_type == "dormant_capital":
            cls._eval_dormant_capital(hyp, results_by_tool)
        elif h_type == "repeat_purchase_decline":
            cls._eval_repeat_purchase(hyp, results_by_tool)
        elif h_type in ("recurring_overhead", "variable_overhead", "opex_impact"):
            cls._eval_expense_impact(hyp, results_by_tool)
        else:
            cls._eval_generic_variance(hyp, results_by_tool)

    @classmethod
    def _eval_category_variance(
        cls,
        hyp: InvestigationHypothesis,
        results_by_tool: dict[str, list[dict[str, Any]]],
    ) -> None:
        variance_results = results_by_tool.get("run_variance_analysis", [])
        cat_result = None
        for res in variance_results:
            if res.get("dimension") == "category":
                cat_result = res
                break
        if not cat_result and variance_results:
            cat_result = variance_results[0]

        if not cat_result:
            hyp.status = HypothesisStatus.INCONCLUSIVE
            hyp.evidence_strength = EvidenceStrength.INSUFFICIENT
            hyp.confidence_reason = "No category variance analysis results available."
            return

        items = (
            cat_result.get("top_negative_contributors", [])
            or cat_result.get("top_positive_contributors", [])
            or cat_result.get("items", [])
        )
        if not items:
            hyp.status = HypothesisStatus.NOT_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.DIRECT
            hyp.confidence_reason = "Category variance breakdown returned zero categorized line items."
            return

        top_item = items[0]
        top_name = top_item.get("entity_name") or top_item.get("entity_id", "Unknown")
        share = abs(float(top_item.get("contribution_to_change_pct", top_item.get("contribution_percentage", 0.0))))
        variance_val = float(top_item.get("absolute_change", top_item.get("variance_amount", 0.0)))

        link = EvidenceLink(
            tool_name="run_variance_analysis",
            metric="category_contribution_share",
            source="sales_and_products",
            value=f"{top_name}: {share:.1f}%",
            contribution_pct=share,
            notes=f"Top category contributor '{top_name}' accounted for {share:.1f}% of total measured variance ({variance_val:,.2f}).",
        )

        if share >= 40.0:
            hyp.status = HypothesisStatus.SUPPORTED
            hyp.evidence_strength = EvidenceStrength.DIRECT
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = (
                f"Direct attribution: '{top_name}' accounted for {share:.1f}% of measured revenue variance."
            )
        elif share >= 20.0:
            hyp.status = HypothesisStatus.PARTIALLY_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.STRONG
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = (
                f"Noticeable concentration: '{top_name}' contributed {share:.1f}% of variance, alongside other categories."
            )
        else:
            hyp.status = HypothesisStatus.NOT_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.MODERATE
            hyp.contradicting_evidence.append(link)
            hyp.confidence_reason = (
                f"Variance was diffuse: largest category '{top_name}' represented only {share:.1f}% of change."
            )

    @classmethod
    def _eval_volume_effect(
        cls,
        hyp: InvestigationHypothesis,
        results_by_tool: dict[str, list[dict[str, Any]]],
    ) -> None:
        pvm_results = results_by_tool.get("run_price_volume_mix", [])
        if not pvm_results:
            hyp.status = HypothesisStatus.INCONCLUSIVE
            hyp.evidence_strength = EvidenceStrength.INSUFFICIENT
            hyp.confidence_reason = "No Price/Volume/Mix decomposition executed."
            return

        res = pvm_results[0]
        vol = abs(float(res.get("volume_effect", 0.0)))
        price = abs(float(res.get("price_effect", 0.0)))
        total = abs(float(res.get("total_variance", 1.0)))

        vol_share = (vol / total * 100) if total > 0 else 0.0
        price_share = (price / total * 100) if total > 0 else 0.0

        link = EvidenceLink(
            tool_name="run_price_volume_mix",
            metric="volume_effect",
            source="sales_line_items",
            value=f"Volume: {vol:,.2f} ({vol_share:.1f}%), Price: {price:,.2f} ({price_share:.1f}%)",
            contribution_pct=vol_share,
            notes=f"Volume effect explained {vol_share:.1f}% of total price/volume/mix variance.",
        )

        if vol_share >= 55.0:
            hyp.status = HypothesisStatus.SUPPORTED
            hyp.evidence_strength = EvidenceStrength.DIRECT
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = (
                f"Volume Effect accounted for {vol_share:.1f}% of total variance, dominating price adjustments ({price_share:.1f}%)."
            )
        elif vol_share >= 30.0:
            hyp.status = HypothesisStatus.PARTIALLY_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.STRONG
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = (
                f"Volume change contributed {vol_share:.1f}% alongside active price effects ({price_share:.1f}%)."
            )
        else:
            hyp.status = HypothesisStatus.NOT_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.DIRECT
            hyp.contradicting_evidence.append(link)
            hyp.confidence_reason = (
                f"Volume Effect explained only {vol_share:.1f}%; Price Effect was the predominant driver ({price_share:.1f}%)."
            )

    @classmethod
    def _eval_mix_effect(
        cls,
        hyp: InvestigationHypothesis,
        results_by_tool: dict[str, list[dict[str, Any]]],
    ) -> None:
        pvm_results = results_by_tool.get("run_price_volume_mix", [])
        if not pvm_results:
            hyp.status = HypothesisStatus.INCONCLUSIVE
            hyp.evidence_strength = EvidenceStrength.INSUFFICIENT
            return

        res = pvm_results[0]
        mix = abs(float(res.get("mix_effect", 0.0)))
        total = abs(float(res.get("total_variance", 1.0)))
        mix_share = (mix / total * 100) if total > 0 else 0.0

        link = EvidenceLink(
            tool_name="run_price_volume_mix",
            metric="mix_effect",
            source="sales_line_items",
            value=f"Mix: {mix:,.2f} ({mix_share:.1f}%)",
            contribution_pct=mix_share,
            notes=f"Mix effect explained {mix_share:.1f}% of total variance.",
        )

        if mix_share >= 25.0:
            hyp.status = HypothesisStatus.SUPPORTED
            hyp.evidence_strength = EvidenceStrength.DIRECT
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = f"Product mix shifting accounted for {mix_share:.1f}% of the total sales variance."
        elif mix_share >= 10.0:
            hyp.status = HypothesisStatus.PARTIALLY_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.MODERATE
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = f"Product mix had a moderate {mix_share:.1f}% contribution."
        else:
            hyp.status = HypothesisStatus.NOT_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.DIRECT
            hyp.contradicting_evidence.append(link)
            hyp.confidence_reason = f"Mix effect was negligible ({mix_share:.1f}% of total variance)."

    @classmethod
    def _eval_price_or_cogs(
        cls,
        hyp: InvestigationHypothesis,
        results_by_tool: dict[str, list[dict[str, Any]]],
    ) -> None:
        pvm_results = results_by_tool.get("run_price_volume_mix", [])
        if pvm_results:
            res = pvm_results[0]
            price = abs(float(res.get("price_effect", 0.0)))
            total = abs(float(res.get("total_variance", 1.0)))
            price_share = (price / total * 100) if total > 0 else 0.0

            link = EvidenceLink(
                tool_name="run_price_volume_mix",
                metric="price_effect",
                source="sales_line_items",
                value=f"Price: {price:,.2f} ({price_share:.1f}%)",
                contribution_pct=price_share,
                notes=f"Price effect explained {price_share:.1f}% of variance.",
            )

            if price_share >= 40.0:
                hyp.status = HypothesisStatus.SUPPORTED
                hyp.evidence_strength = EvidenceStrength.DIRECT
                hyp.supporting_evidence.append(link)
                hyp.confidence_reason = f"Realized price changes accounted for {price_share:.1f}% of the total measured variance."
                return

        # Check financial summary COGS ratio
        fin_results = results_by_tool.get("get_financial_summary", [])
        if fin_results:
            res = fin_results[0]
            cogs = float(res.get("cogs", {}).get("value", 0.0))
            sales = float(res.get("net_sales", {}).get("value", 1.0))
            cogs_ratio = (cogs / sales * 100) if sales > 0 else 0.0

            link = EvidenceLink(
                tool_name="get_financial_summary",
                metric="cogs_ratio",
                source="sales_and_products",
                value=f"COGS Ratio: {cogs_ratio:.1f}%",
                notes=f"COGS constituted {cogs_ratio:.1f}% of net sales.",
            )
            if cogs_ratio >= 60.0:
                hyp.status = HypothesisStatus.SUPPORTED
                hyp.evidence_strength = EvidenceStrength.STRONG
                hyp.supporting_evidence.append(link)
                hyp.confidence_reason = f"High COGS absorption ({cogs_ratio:.1f}% of net revenue) compressed profitability."
                return

        hyp.status = HypothesisStatus.INCONCLUSIVE
        hyp.evidence_strength = EvidenceStrength.INSUFFICIENT
        hyp.confidence_reason = "Insufficient cost or price variance evidence."

    @classmethod
    def _eval_stockout_constraint(
        cls,
        hyp: InvestigationHypothesis,
        results_by_tool: dict[str, list[dict[str, Any]]],
    ) -> None:
        inv_results = results_by_tool.get("get_inventory_overview", [])
        if not inv_results:
            hyp.status = HypothesisStatus.INCONCLUSIVE
            hyp.evidence_strength = EvidenceStrength.INSUFFICIENT
            hyp.confidence_reason = "No inventory health evaluation performed."
            return

        res = inv_results[0]
        out_of_stock = int(res.get("out_of_stock_count", 0))
        low_stock = int(res.get("low_stock_count", 0))

        link = EvidenceLink(
            tool_name="get_inventory_overview",
            metric="stockout_count",
            source="inventory",
            value=f"Stockouts: {out_of_stock}, Low-Stock: {low_stock}",
            notes=f"Observed {out_of_stock} out-of-stock items and {low_stock} items under reorder threshold.",
        )

        if out_of_stock > 0 or low_stock > 0:
            hyp.status = HypothesisStatus.PARTIALLY_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.MODERATE
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = (
                f"Current stock exhibits {out_of_stock} stockouts and {low_stock} low-stock alerts, "
                "which may constrain order fulfillment."
            )
            hyp.limitations.append(
                "Current stock reflects snapshot state; historical daily stockout logs are unobserved."
            )
        else:
            hyp.status = HypothesisStatus.NOT_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.DIRECT
            hyp.contradicting_evidence.append(link)
            hyp.confidence_reason = "Current inventory shows 0 stockouts and 0 items below reorder thresholds."

    @classmethod
    def _eval_dormant_capital(
        cls,
        hyp: InvestigationHypothesis,
        results_by_tool: dict[str, list[dict[str, Any]]],
    ) -> None:
        velocity_results = results_by_tool.get("get_inventory_velocity", [])
        if not velocity_results:
            hyp.status = HypothesisStatus.INCONCLUSIVE
            hyp.evidence_strength = EvidenceStrength.INSUFFICIENT
            return

        res = velocity_results[0]
        dormant = int(res.get("dormant_count", 0))
        slow = int(res.get("slow_moving_count", 0))
        total = dormant + slow + int(res.get("medium_velocity_count", 0)) + int(res.get("high_velocity_count", 0))
        pct = (dormant + slow) / total * 100 if total > 0 else 0.0

        link = EvidenceLink(
            tool_name="get_inventory_velocity",
            metric="dormant_and_slow_skus",
            source="inventory_and_sales",
            value=f"{dormant} dormant, {slow} slow ({pct:.1f}%)",
            notes=f"{pct:.1f}% of catalog SKUs exhibit dormant or slow-moving velocity.",
        )

        if pct >= 30.0:
            hyp.status = HypothesisStatus.SUPPORTED
            hyp.evidence_strength = EvidenceStrength.STRONG
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = f"{pct:.1f}% of catalog SKUs are dormant or slow-moving, tying up working capital."
        else:
            hyp.status = HypothesisStatus.NOT_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.MODERATE
            hyp.contradicting_evidence.append(link)
            hyp.confidence_reason = f"Dormant and slow inventory represents only {pct:.1f}% of active SKUs."

    @classmethod
    def _eval_repeat_purchase(
        cls,
        hyp: InvestigationHypothesis,
        results_by_tool: dict[str, list[dict[str, Any]]],
    ) -> None:
        repeat_results = results_by_tool.get("get_repeat_purchase", [])
        if not repeat_results:
            hyp.status = HypothesisStatus.INCONCLUSIVE
            hyp.evidence_strength = EvidenceStrength.INSUFFICIENT
            return

        res = repeat_results[0]
        rate = float(res.get("repeat_purchase_rate", 0.0))
        link = EvidenceLink(
            tool_name="get_repeat_purchase",
            metric="repeat_purchase_rate",
            source="sales",
            value=f"{rate:.1f}%",
            notes=f"Measured repeat purchase rate was {rate:.1f}%.",
        )

        if rate < 30.0:
            hyp.status = HypothesisStatus.SUPPORTED
            hyp.evidence_strength = EvidenceStrength.STRONG
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = f"Low repeat purchase rate ({rate:.1f}%) indicates limited recurring customer retention."
        else:
            hyp.status = HypothesisStatus.PARTIALLY_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.MODERATE
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = f"Repeat purchase rate remained relatively healthy at {rate:.1f}%."

    @classmethod
    def _eval_expense_impact(
        cls,
        hyp: InvestigationHypothesis,
        results_by_tool: dict[str, list[dict[str, Any]]],
    ) -> None:
        expense_results = results_by_tool.get("get_expense_analytics", [])
        if not expense_results:
            hyp.status = HypothesisStatus.INCONCLUSIVE
            hyp.evidence_strength = EvidenceStrength.INSUFFICIENT
            return

        res = expense_results[0]
        rec_share = float(res.get("recurring_share_pct", 0.0))
        total_exp = float(res.get("total_expenses", 0.0))

        link = EvidenceLink(
            tool_name="get_expense_analytics",
            metric="recurring_overhead_share",
            source="expenses",
            value=f"Recurring: {rec_share:.1f}%, Total: {total_exp:,.2f}",
            notes=f"Recurring operational expenses represented {rec_share:.1f}% of total expenses.",
        )

        if hyp.type == "recurring_overhead" and rec_share >= 60.0:
            hyp.status = HypothesisStatus.SUPPORTED
            hyp.evidence_strength = EvidenceStrength.STRONG
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = f"Recurring contractual overhead constituted {rec_share:.1f}% of all operational expenditure."
        elif hyp.type == "variable_overhead" and rec_share < 50.0:
            hyp.status = HypothesisStatus.SUPPORTED
            hyp.evidence_strength = EvidenceStrength.STRONG
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = f"Variable operational costs represented {100 - rec_share:.1f}% of total expenses."
        else:
            hyp.status = HypothesisStatus.PARTIALLY_SUPPORTED
            hyp.evidence_strength = EvidenceStrength.MODERATE
            hyp.supporting_evidence.append(link)
            hyp.confidence_reason = f"Expense structure showed balanced recurring ({rec_share:.1f}%) and variable components."

    @classmethod
    def _eval_generic_variance(
        cls,
        hyp: InvestigationHypothesis,
        results_by_tool: dict[str, list[dict[str, Any]]],
    ) -> None:
        if "run_variance_analysis" in results_by_tool:
            hyp.status = HypothesisStatus.SUPPORTED
            hyp.evidence_strength = EvidenceStrength.MODERATE
            hyp.confidence_reason = "Empirical variance decomposition completed."
        else:
            hyp.status = HypothesisStatus.INCONCLUSIVE
            hyp.evidence_strength = EvidenceStrength.INSUFFICIENT
