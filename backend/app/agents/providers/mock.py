"""Deterministic, offline Mock LLM Provider for testing and offline environments.

Provides reproducible intent classification, structured analysis planning, and evidence-grounded
explanations without making external API calls or incurring costs.
"""

from typing import Any

from app.agents.providers.base import BaseLLMProvider
from app.agents.state.models import (
    AnalysisPlan,
    ExplanationLevel,
    IntentCategory,
    IntentResult,
    PlanStep,
)


class MockLLMProvider(BaseLLMProvider):
    """
    Deterministic offline LLM provider.
    
    Adheres strictly to the NEXUS core principle: the model is an orchestrator and explainer,
    never an independent calculator. Uses deterministic rules to plan tools and explains
    only figures that exist within returned tool results.
    """

    def classify_intent(
        self, query: str, supported_intents: list[str]
    ) -> IntentResult:
        q = query.lower()

        # Check for unsupported questions (chit-chat, forecasting, generic requests)
        unsupported_keywords = [
            "joke", "poem", "weather", "recipe", "song", "who are you",
            "predict", "forecast", "machine learning", "stock price", "recommend stocks"
        ]
        if any(w in q for w in unsupported_keywords):
            return IntentResult(
                category=IntentCategory.UNSUPPORTED,
                confidence=1.0,
                reasoning="Query requests non-deterministic or out-of-scope capabilities."
            )

        # Check for statistical analysis
        if any(w in q for w in ["correlation", "correlate", "hypothesis", "t-test", "ttest", "p-value", "significance"]):
            return IntentResult(
                category=IntentCategory.STATISTICAL_ANALYSIS,
                confidence=0.95,
                reasoning="Query requests bivariate statistical correlation or hypothesis testing."
            )

        # Check for diagnostic analysis (variance, why did change, decline, contributors, PVM)
        if any(w in q for w in ["why did", "contributed most", "contributing", "contributor", "decline", "variance", "price volume mix", "pvm", "decomposition"]):
            return IntentResult(
                category=IntentCategory.DIAGNOSTIC_ANALYSIS,
                confidence=0.95,
                reasoning="Query requests root cause contribution or variance decomposition."
            )

        # Check for inventory analysis
        if any(w in q for w in ["inventory", "stock", "turnover", "velocity", "reorder", "warehouse", "dormant", "slow-moving"]):
            return IntentResult(
                category=IntentCategory.INVENTORY_ANALYSIS,
                confidence=0.95,
                reasoning="Query requests inventory health, valuation, turnover, or SKU velocity."
            )

        # Check for customer analysis
        if any(w in q for w in ["customer", "rfm", "cohort", "repeat purchase", "one-time", "retention", "segment"]):
            return IntentResult(
                category=IntentCategory.CUSTOMER_ANALYSIS,
                confidence=0.95,
                reasoning="Query requests customer segmentation, retention, or behavioral metrics."
            )

        # Check for expense analysis
        if any(w in q for w in ["expense", "expenses", "opex", "overhead", "operating costs", "recurring"]):
            return IntentResult(
                category=IntentCategory.EXPENSE_ANALYSIS,
                confidence=0.95,
                reasoning="Query requests operating expense analysis or recurring cost shares."
            )

        # Check for product / category analysis
        if any(w in q for w in ["product", "sku", "category", "categories", "best selling", "top product", "top products", "ranking"]):
            return IntentResult(
                category=IntentCategory.PRODUCT_ANALYSIS,
                confidence=0.95,
                reasoning="Query requests product rankings, SKU velocity, or category distribution."
            )

        # Check for trend / timeseries
        if any(w in q for w in ["trend", "over time", "monthly sales", "timeseries", "progression", "by month", "by day", "by quarter"]):
            return IntentResult(
                category=IntentCategory.TREND,
                confidence=0.95,
                reasoning="Query requests chronological metric aggregation over time."
            )

        # Check for comparison
        if any(w in q for w in ["change compared", "growth", "vs previous", "vs last", "compared to", "increase", "decrease"]):
            return IntentResult(
                category=IntentCategory.COMPARISON,
                confidence=0.95,
                reasoning="Query requests period-over-period comparative analysis."
            )

        # Default to metric lookup for business metrics
        if any(w in q for w in ["revenue", "sales", "profit", "cogs", "orders", "units", "margin", "aov", "average order"]):
            return IntentResult(
                category=IntentCategory.METRIC_LOOKUP,
                confidence=0.90,
                reasoning="Query requests lookup of standard business financial metrics."
            )

        # If query is completely unknown or unstructured
        return IntentResult(
            category=IntentCategory.UNSUPPORTED,
            confidence=0.50,
            reasoning="Query does not match any known deterministic analytical domain."
        )

    def create_plan(
        self,
        query: str,
        intent: IntentCategory,
        available_tools: list[dict[str, Any]],
        resolved_dates: dict[str, Any],
    ) -> AnalysisPlan:
        q = query.lower()
        d_from = resolved_dates.get("date_from")
        d_to = resolved_dates.get("date_to")
        c_from = resolved_dates.get("comparison_date_from")
        c_to = resolved_dates.get("comparison_date_to")
        granularity = resolved_dates.get("granularity", "monthly")

        # 1. Diagnostic analysis (frequently multi-step)
        if intent == IntentCategory.DIAGNOSTIC_ANALYSIS:
            if "price volume mix" in q or "pvm" in q or "decomposition" in q:
                return AnalysisPlan(
                    goal="Decompose sales change into Price, Volume, and Mix effects",
                    steps=[
                        PlanStep(
                            step_index=0,
                            tool_name="run_price_volume_mix",
                            purpose="Perform Price/Volume/Mix decomposition reconciling period sales variance",
                            arguments={"date_from": d_from, "date_to": d_to, "comparison_date_from": c_from, "comparison_date_to": c_to}
                        )
                    ],
                    context_dates=resolved_dates,
                )
            
            dimension = "product"
            if "category" in q:
                dimension = "category"
            elif "segment" in q or "customer" in q:
                dimension = "customer_segment"

            return AnalysisPlan(
                goal=f"Diagnose revenue variance and identify top contributors by {dimension}",
                steps=[
                    PlanStep(
                        step_index=0,
                        tool_name="get_financial_summary",
                        purpose="Evaluate macro revenue change and period-over-period variance",
                        arguments={"date_from": d_from, "date_to": d_to, "comparison_date_from": c_from, "comparison_date_to": c_to}
                    ),
                    PlanStep(
                        step_index=1,
                        tool_name="run_variance_analysis",
                        purpose=f"Dissect revenue variance by {dimension} and identify top positive/negative contributors",
                        arguments={"date_from": d_from, "date_to": d_to, "comparison_date_from": c_from, "comparison_date_to": c_to, "dimension": dimension}
                    ),
                ],
                context_dates=resolved_dates,
            )

        # 2. Product Analysis
        if intent == IntentCategory.PRODUCT_ANALYSIS:
            if "category" in q or "categories" in q:
                metric = "profit" if "profit" in q else "revenue"
                return AnalysisPlan(
                    goal="Evaluate category performance breakdown",
                    steps=[
                        PlanStep(
                            step_index=0,
                            tool_name="get_category_breakdown",
                            purpose="Calculate revenue and volume distribution across product categories",
                            arguments={"date_from": d_from, "date_to": d_to, "metric": metric}
                        )
                    ],
                    context_dates=resolved_dates,
                )
            
            ranking_metric = "revenue"
            if "margin" in q:
                ranking_metric = "margin"
            elif "profit" in q:
                ranking_metric = "profit"
            elif "unit" in q:
                ranking_metric = "units"
            elif "order" in q:
                ranking_metric = "orders"

            return AnalysisPlan(
                goal=f"Rank top products deterministically by {ranking_metric}",
                steps=[
                    PlanStep(
                        step_index=0,
                        tool_name="get_product_rankings",
                        purpose=f"Retrieve ranked products sorted by {ranking_metric}",
                        arguments={"date_from": d_from, "date_to": d_to, "ranking_metric": ranking_metric, "limit": 10}
                    )
                ],
                context_dates=resolved_dates,
            )

        # 3. Customer Analysis
        if intent == IntentCategory.CUSTOMER_ANALYSIS:
            if "rfm" in q:
                return AnalysisPlan(
                    goal="Compute customer RFM quintile segmentation",
                    steps=[
                        PlanStep(
                            step_index=0,
                            tool_name="get_rfm_analysis",
                            purpose="Calculate Recency, Frequency, and Monetary scores and quintile bins",
                            arguments={"date_from": d_from, "date_to": d_to}
                        )
                    ],
                    context_dates=resolved_dates,
                )
            if "cohort" in q:
                return AnalysisPlan(
                    goal="Evaluate customer cohort retention and cumulative spend",
                    steps=[
                        PlanStep(
                            step_index=0,
                            tool_name="get_cohort_analysis",
                            purpose="Track retention across customer acquisition cohorts over subsequent months",
                            arguments={"date_from": d_from, "date_to": d_to}
                        )
                    ],
                    context_dates=resolved_dates,
                )
            if "repeat" in q or "one-time" in q:
                return AnalysisPlan(
                    goal="Calculate customer repeat purchase metrics",
                    steps=[
                        PlanStep(
                            step_index=0,
                            tool_name="get_repeat_purchase",
                            purpose="Compute repeat purchase rate and order frequency distribution",
                            arguments={"date_from": d_from, "date_to": d_to}
                        )
                    ],
                    context_dates=resolved_dates,
                )

            return AnalysisPlan(
                goal="Evaluate customer segment distribution and activity",
                steps=[
                    PlanStep(
                        step_index=0,
                        tool_name="get_customer_segments",
                        purpose="Aggregate customer orders and revenue by segment",
                        arguments={"date_from": d_from, "date_to": d_to}
                    )
                ],
                context_dates=resolved_dates,
            )

        # 4. Inventory Analysis
        if intent == IntentCategory.INVENTORY_ANALYSIS:
            if "turnover" in q or "dsi" in q or "days sales" in q:
                return AnalysisPlan(
                    goal="Compute inventory turnover ratio and Days Sales of Inventory (DSI)",
                    steps=[
                        PlanStep(
                            step_index=0,
                            tool_name="get_inventory_turnover",
                            purpose="Calculate inventory turnover ratio and DSI",
                            arguments={"date_from": d_from, "date_to": d_to}
                        )
                    ],
                    context_dates=resolved_dates,
                )
            if "velocity" in q or "slow" in q or "dormant" in q or "fast" in q:
                return AnalysisPlan(
                    goal="Evaluate product sales velocity and run rates",
                    steps=[
                        PlanStep(
                            step_index=0,
                            tool_name="get_inventory_velocity",
                            purpose="Identify fast-moving, slow-moving, and dormant SKUs",
                            arguments={"date_from": d_from, "date_to": d_to}
                        )
                    ],
                    context_dates=resolved_dates,
                )

            return AnalysisPlan(
                goal="Evaluate current inventory health, valuation, and stock alerts",
                steps=[
                    PlanStep(
                        step_index=0,
                        tool_name="get_inventory_overview",
                        purpose="Assess total inventory valuation, out-of-stock items, and reorder alerts",
                        arguments={}
                    )
                ],
                context_dates=resolved_dates,
            )

        # 5. Expense Analysis
        if intent == IntentCategory.EXPENSE_ANALYSIS:
            return AnalysisPlan(
                goal="Analyze operating expenses and recurring overhead shares",
                steps=[
                    PlanStep(
                        step_index=0,
                        tool_name="get_expense_analytics",
                        purpose="Aggregate operating expenses by category with recurring vs variable breakdown",
                        arguments={"date_from": d_from, "date_to": d_to, "comparison_date_from": c_from, "comparison_date_to": c_to}
                    )
                ],
                context_dates=resolved_dates,
            )

        # 6. Trend / Timeseries
        if intent == IntentCategory.TREND:
            metric = "revenue"
            if "order" in q:
                metric = "orders"
            elif "unit" in q:
                metric = "units"
            elif "profit" in q:
                metric = "profit"

            return AnalysisPlan(
                goal=f"Aggregate {metric} timeseries across {granularity} intervals",
                steps=[
                    PlanStep(
                        step_index=0,
                        tool_name="get_sales_timeseries",
                        purpose=f"Calculate chronological {metric} buckets with growth rates",
                        arguments={"date_from": d_from, "date_to": d_to, "metric": metric, "granularity": granularity}
                    )
                ],
                context_dates=resolved_dates,
            )

        # 7. Statistical Analysis
        if intent == IntentCategory.STATISTICAL_ANALYSIS:
            if "hypothesis" in q or "ttest" in q or "t-test" in q or "segment" in q:
                # Find segment names if present, else default
                return AnalysisPlan(
                    goal="Perform two-sample Welch's t-test comparing customer segment order values",
                    steps=[
                        PlanStep(
                            step_index=0,
                            tool_name="run_hypothesis_test",
                            purpose="Compare order value distributions between VIP and Standard segments",
                            arguments={"group1_segment": "VIP", "group2_segment": "Standard", "date_from": d_from, "date_to": d_to}
                        )
                    ],
                    context_dates=resolved_dates,
                )

            return AnalysisPlan(
                goal="Compute bivariate correlation coefficient and p-value",
                steps=[
                    PlanStep(
                        step_index=0,
                        tool_name="run_correlation",
                        purpose="Calculate Pearson correlation between order volume and discount amount",
                        arguments={"variable_x": "quantity", "variable_y": "discount_amount", "date_from": d_from, "date_to": d_to}
                    )
                ],
                context_dates=resolved_dates,
            )

        # 8. Metric Lookup & Comparison (Financial Summary)
        return AnalysisPlan(
            goal="Evaluate executive financial metrics scorecard",
            steps=[
                PlanStep(
                    step_index=0,
                    tool_name="get_financial_summary",
                    purpose="Calculate gross sales, net revenue, margins, COGS, and period comparison",
                    arguments={"date_from": d_from, "date_to": d_to, "comparison_date_from": c_from, "comparison_date_to": c_to}
                )
            ],
            context_dates=resolved_dates,
        )

    def explain_results(
        self,
        query: str,
        plan: AnalysisPlan | None,
        tool_results: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        explanation_level: ExplanationLevel,
    ) -> str:
        if not tool_results:
            return "No analytical results were returned to synthesize an answer."

        # Aggregate evidence summaries and find key outputs
        lines = []

        # Check what tools executed
        tools_executed = [r.get("tool") for r in tool_results]

        # 1. Variance Analysis / Diagnostic
        if "run_variance_analysis" in tools_executed:
            var_res = next((r["result"] for r in tool_results if r["tool"] == "run_variance_analysis"), {})
            tot_var = var_res.get("total_variance", 0.0)
            pct_chg = var_res.get("percentage_change")
            direction = var_res.get("direction", "unchanged")
            dim = var_res.get("dimension", "dimension")
            pos_contribs = var_res.get("top_positive_contributors", [])
            neg_contribs = var_res.get("top_negative_contributors", [])

            pct_str = f"{pct_chg:+.2f}%" if pct_chg is not None else "N/A"
            lines.append(f"Revenue variance analysis indicates a total {direction} of ${abs(float(tot_var)):,.2f} ({pct_str}) across the analyzed period.")
            if neg_contribs:
                top_neg = neg_contribs[0]
                lines.append(f"The largest negative contribution came from {dim} '{top_neg.get('entity_name')}', with an absolute change of -${abs(float(top_neg.get('absolute_change', 0))):,.2f}.")
            if pos_contribs:
                top_pos = pos_contribs[0]
                lines.append(f"The largest positive offsetting contribution came from {dim} '{top_pos.get('entity_name')}', which grew by +${float(top_pos.get('absolute_change', 0)):,.2f}.")

            lines.append("\nNote: Contribution analysis measures arithmetic association across dimensions and does not establish causality.")

        # 2. Price Volume Mix
        elif "run_price_volume_mix" in tools_executed:
            pvm = next((r["result"] for r in tool_results if r["tool"] == "run_price_volume_mix"), {})
            tot = pvm.get("total_variance", 0.0)
            vol = pvm.get("volume_effect", 0.0)
            prc = pvm.get("price_effect", 0.0)
            mix = pvm.get("mix_effect", 0.0)
            lines.append(f"Price / Volume / Mix decomposition reconciles a total variance of ${float(tot):,.2f}:")
            lines.append(f"- Volume Effect: ${float(vol):,.2f}")
            lines.append(f"- Price Effect: ${float(prc):,.2f}")
            lines.append(f"- Mix Effect: ${float(mix):,.2f}")

        # 3. Product Rankings
        elif "get_product_rankings" in tools_executed:
            prod_res = next((r["result"] for r in tool_results if r["tool"] == "get_product_rankings"), {})
            items = prod_res.get("items", [])
            ranking_metric = prod_res.get("ranking_metric", "revenue")
            lines.append(f"Product rankings by {ranking_metric}:")
            for idx, item in enumerate(items[:5], 1):
                val = item.get("revenue") if ranking_metric == "revenue" else item.get(ranking_metric)
                lines.append(f"{idx}. {item.get('name')} (SKU: {item.get('sku')}): ${float(val or 0):,.2f}" if ranking_metric in ("revenue", "profit") else f"{idx}. {item.get('name')} ({ranking_metric}: {val})")

        # 4. Financial Summary
        elif "get_financial_summary" in tools_executed:
            fin = next((r["result"] for r in tool_results if r["tool"] == "get_financial_summary"), {})
            net_sales = fin.get("net_sales", {}).get("value")
            gross_profit = fin.get("gross_profit", {}).get("value")
            gross_margin = fin.get("gross_margin", {}).get("value")
            orders = fin.get("orders", {}).get("value")
            aov = fin.get("average_order_value", {}).get("value")
            net_profit = fin.get("net_profit", {}).get("value")
            comp = fin.get("net_sales", {}).get("comparison")

            sales_val = float(net_sales) if net_sales is not None else 0.0
            lines.append(f"Net Revenue was ${sales_val:,.2f} across {int(orders or 0):,} orders, with an Average Order Value (AOV) of ${float(aov or 0):,.2f}.")
            lines.append(f"Gross Profit totaled ${float(gross_profit or 0):,.2f} (Gross Margin: {float(gross_margin or 0):.2f}%), yielding a Net Profit of ${float(net_profit or 0):,.2f}.")

            if comp:
                chg = comp.get("percentage_change")
                chg_str = f"{chg:+.2f}%" if chg is not None else "undefined"
                lines.append(f"Compared to the preceding baseline, revenue changed by {chg_str} (${float(comp.get('absolute_change', 0)):+,.2f}).")

        # 5. Inventory Overview / Turnover
        elif "get_inventory_overview" in tools_executed:
            inv = next((r["result"] for r in tool_results if r["tool"] == "get_inventory_overview"), {})
            val = inv.get("total_inventory_valuation", 0.0)
            low = inv.get("low_stock_count", 0)
            out = inv.get("out_of_stock_count", 0)
            lines.append(f"Total current inventory valuation is ${float(val):,.2f} across {inv.get('total_skus', 0)} SKUs.")
            lines.append(f"Inventory alerts: {low} products are below their reorder threshold, and {out} products are completely out of stock.")

        # 6. Correlation / Statistics
        elif "run_correlation" in tools_executed:
            corr = next((r["result"] for r in tool_results if r["tool"] == "run_correlation"), {})
            coeff = corr.get("correlation_coefficient")
            p_val = corr.get("p_value")
            method = corr.get("method", "pearson").upper()
            sig = "statistically significant" if corr.get("is_statistically_significant") else "not statistically significant"
            lines.append(f"The {method} correlation coefficient is {coeff:.4f} (p-value: {p_val:.4e}, N={corr.get('sample_size')}), which is {sig} at alpha = 0.05.")
            lines.append(f"\nMethodological constraint: {corr.get('causation_warning')}")

        # 7. Fallback generic summary
        else:
            first_res = tool_results[0].get("result", {})
            lines.append(f"Analysis completed successfully using {tools_executed[0]}.")
            if isinstance(first_res, dict):
                lines.append(f"Key metrics: { {k: v for k, v in list(first_res.items())[:4]} }")

        # Format according to requested ExplanationLevel
        if explanation_level == ExplanationLevel.SIMPLE:
            return "\n".join(lines[:2])

        if explanation_level == ExplanationLevel.MANAGER:
            # Concise summary with key figures and business context
            return "\n".join(lines)

        if explanation_level in (ExplanationLevel.ANALYST, ExplanationLevel.TECHNICAL):
            # Include audit trail, formulas, and limitations
            full_text = "\n".join(lines) + "\n\n--- Traceability & Evidence ---"
            for ev in evidence:
                full_text += f"\n• Metric: {ev.get('metric')}"
                full_text += f"\n  Source tables: {', '.join(ev.get('source_tables', []))}"
                full_text += f"\n  Formula/Rule: {ev.get('calculation')}"
                if ev.get("limitations"):
                    full_text += f"\n  Limitations: {'; '.join(ev.get('limitations', []))}"
            return full_text

        return "\n".join(lines)
