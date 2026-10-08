"""Deterministic, offline Mock LLM Provider for testing and offline environments.

Provides reproducible intent classification, structured analysis planning, and evidence-grounded
explanations without making external API calls or incurring costs.
"""

import json
import time
from typing import Any, TypeVar
from pydantic import BaseModel

from app.agents.providers.base import BaseLLMProvider
from app.agents.providers.models import (
    LLMRequest,
    LLMResponse,
    LLMTaskCategory,
    ModelTier,
    TokenUsage,
)
from app.agents.state.models import (
    AnalysisPlan,
    ExplanationLevel,
    IntentCategory,
    IntentResult,
    PlanStep,
)

T = TypeVar("T", bound=BaseModel)


def _extract_currency_symbol(tool_results: list[dict[str, Any]], default: str = "$") -> str:
    """Extract currency symbol from tool results if present."""
    for tr in tool_results:
        res = tr.get("result", {})
        if isinstance(res, dict):
            if res.get("currency_symbol"):
                return str(res["currency_symbol"])
            for field in ["net_sales", "gross_sales", "average_order_value"]:
                val = res.get(field)
                if isinstance(val, dict):
                    fmt = str(val.get("formatted", ""))
                    if fmt and fmt[0] in ("$", "₹", "€", "£", "¥"):
                        return fmt[0]
    return default


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

        # Check for business profile / workspace metadata
        from app.decisions.taxonomy import is_business_profile_query
        if is_business_profile_query(query):
            return IntentResult(
                category=IntentCategory.BUSINESS_PROFILE,
                confidence=1.0,
                reasoning="Query requests active tenant business workspace profile metadata."
            )

        # Check for predictive forecasting (Phase 7)
        forecast_keywords = ["forecast", "predict", "projection", "look like next", "expected revenue", "expected sales", "expected units", "expected order"]
        if any(w in q for w in forecast_keywords):
            return IntentResult(
                category=IntentCategory.FORECASTING,
                confidence=0.95,
                reasoning="Query requests deterministic time-series forecasting."
            )

        # Check for unsupported questions (chit-chat, speculative decisions, generic requests)
        unsupported_keywords = [
            "joke", "poem", "weather", "recipe", "song", "who are you",
            "machine learning", "stock price", "recommend stocks", "crypto"
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

        # Business Profile context
        if intent == IntentCategory.BUSINESS_PROFILE:
            return AnalysisPlan(
                goal=f"Retrieve verified tenant business workspace profile for: {query}",
                steps=[
                    PlanStep(
                        step_index=0,
                        tool_name="get_business_profile",
                        purpose="Retrieve verified business name, industry, country, reporting currency, timezone, and fiscal year",
                        arguments={},
                    )
                ],
                context_dates=resolved_dates,
            )

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
        business_context: str | None = None,
    ) -> str:
        if not tool_results:
            if business_context:
                return f"Verified Business Context:\n\n{business_context}"
            return "No analytical results were returned to synthesize an answer."

        # Aggregate evidence summaries and find key outputs
        lines = []

        curr_sym = _extract_currency_symbol(tool_results, default="$")

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
            lines.append(f"Revenue variance analysis indicates a total {direction} of {curr_sym}{abs(float(tot_var)):,.2f} ({pct_str}) across the analyzed period.")
            if neg_contribs:
                top_neg = neg_contribs[0]
                lines.append(f"The largest negative contribution came from {dim} '{top_neg.get('entity_name')}', with an absolute change of -{curr_sym}{abs(float(top_neg.get('absolute_change', 0))):,.2f}.")
            if pos_contribs:
                top_pos = pos_contribs[0]
                lines.append(f"The largest positive offsetting contribution came from {dim} '{top_pos.get('entity_name')}', which grew by +{curr_sym}{float(top_pos.get('absolute_change', 0)):,.2f}.")

            lines.append("\nNote: Contribution analysis measures arithmetic association across dimensions and does not establish causality.")

        # 2. Price Volume Mix
        elif "run_price_volume_mix" in tools_executed:
            pvm = next((r["result"] for r in tool_results if r["tool"] == "run_price_volume_mix"), {})
            tot = pvm.get("total_variance", 0.0)
            vol = pvm.get("volume_effect", 0.0)
            prc = pvm.get("price_effect", 0.0)
            mix = pvm.get("mix_effect", 0.0)
            lines.append(f"Price / Volume / Mix decomposition reconciles a total variance of {curr_sym}{float(tot):,.2f}:")
            lines.append(f"- Volume Effect: {curr_sym}{float(vol):,.2f}")
            lines.append(f"- Price Effect: {curr_sym}{float(prc):,.2f}")
            lines.append(f"- Mix Effect: {curr_sym}{float(mix):,.2f}")

        # 3. Product Rankings
        elif "get_product_rankings" in tools_executed:
            prod_res = next((r["result"] for r in tool_results if r["tool"] == "get_product_rankings"), {})
            items = prod_res.get("items", [])
            ranking_metric = prod_res.get("ranking_metric", "revenue")
            lines.append(f"Product rankings by {ranking_metric}:")
            for idx, item in enumerate(items[:5], 1):
                val = item.get("revenue") if ranking_metric == "revenue" else item.get(ranking_metric)
                lines.append(f"{idx}. {item.get('name')} (SKU: {item.get('sku')}): {curr_sym}{float(val or 0):,.2f}" if ranking_metric in ("revenue", "profit") else f"{idx}. {item.get('name')} ({ranking_metric}: {val})")

        # 4. Financial Summary
        elif "get_financial_summary" in tools_executed:
            fin = next((r["result"] for r in tool_results if r["tool"] == "get_financial_summary"), {})
            net_sales = fin.get("net_sales", {}).get("value")
            gross_profit = fin.get("gross_profit", {}).get("value")
            gross_margin = fin.get("gross_margin", {}).get("value")
            cogs = fin.get("cogs", {}).get("value")
            orders = fin.get("orders", {}).get("value")
            aov = fin.get("average_order_value", {}).get("value")
            net_profit = fin.get("net_profit", {}).get("value")
            comp = fin.get("net_sales", {}).get("comparison")

            sales_val = float(net_sales) if net_sales is not None else 0.0
            aov_val = float(aov) if aov is not None else 0.0
            lines.append(f"Net Revenue was {curr_sym}{sales_val:,.2f} across {int(orders or 0):,} orders, with an Average Order Value (AOV) of {curr_sym}{aov_val:,.2f}.")

            if gross_profit is not None and gross_margin is not None:
                lines.append(
                    f"Gross Profit totaled {curr_sym}{float(gross_profit):,.2f} "
                    f"(Gross Margin: {float(gross_margin):.2f}%), yielding a Net Profit of {curr_sym}{float(net_profit or 0):,.2f}."
                )
            else:
                lines.append(
                    "Gross Profit and Gross Margin are currently incomplete / unavailable because catalog product unit costs (COGS) are missing. "
                    "Zero COGS is not assumed to avoid fabricated margins."
                )
                if net_profit is not None:
                    lines.append(f"Net Profit totaled {curr_sym}{float(net_profit):,.2f}.")
                else:
                    lines.append("Net Profit is also marked incomplete as it depends on product cost data.")

            if comp:
                chg = comp.get("percentage_change")
                chg_str = f"{chg:+.2f}%" if chg is not None else "undefined"
                abs_val = comp.get("absolute_change")
                abs_str = f"{curr_sym}{float(abs_val):+,.2f}" if abs_val is not None else "N/A"
                lines.append(f"Compared to the preceding baseline, revenue changed by {chg_str} ({abs_str}).")

            if plan and plan.context_dates and plan.context_dates.get("is_far_future"):
                date_str = f"{plan.context_dates.get('date_from')} to {plan.context_dates.get('date_to')}"
                lines.append(f"Temporal Boundary Notice: The requested date range ({date_str}) is in the far future and beyond the historical operational horizon of the enterprise dataset (transactions recorded through 2024). No historical transactions exist for this period. To project future revenue, request a time-series forecast.")
            elif int(orders or 0) == 0:
                lines.append("Note: no transactional records in specified temporal range.")

        # 5. Inventory Overview / Turnover
        elif "get_inventory_overview" in tools_executed:
            inv = next((r["result"] for r in tool_results if r["tool"] == "get_inventory_overview"), {})
            val = inv.get("total_inventory_valuation", 0.0)
            low = inv.get("low_stock_count", 0)
            out = inv.get("out_of_stock_count", 0)
            lines.append(f"Total current inventory valuation is {curr_sym}{float(val):,.2f} across {inv.get('total_skus', 0)} SKUs.")
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

        # 7. Business Profile
        elif "get_business_profile" in tools_executed:
            prof = next((r["result"] for r in tool_results if r["tool"] == "get_business_profile"), {})
            name = prof.get("name")
            industry = prof.get("industry")
            country = prof.get("country")
            currency = prof.get("currency")
            tz = prof.get("timezone")
            fy_start = prof.get("fiscal_year_start")
            fy_month = prof.get("fiscal_year_start_month", f"Month {fy_start}")

            lines.append("Verified Active Business Profile:")
            lines.append(f"• Business Name: {name}")
            lines.append(f"• Industry: {industry}")
            lines.append(f"• Country: {country}")
            lines.append(f"• Reporting Currency: {currency}")
            lines.append(f"• Timezone: {tz}")
            lines.append(f"• Fiscal Year Start: {fy_month} (Month {fy_start})")
            lines.append("\nSource: Active Business Profile (database verified tenant record).")

        # 8. Fallback generic summary
        else:
            first_res = tool_results[0].get("result", {})
            tool_name = tools_executed[0] or "analytical_tool"
            lines.append(f"Analysis completed successfully using {tool_name}.")
            if isinstance(first_res, dict):
                lines.append(f"Key metrics: { {k: v for k, v in list(first_res.items())[:4]} }")

        if "get_business_profile" in tools_executed:
            if explanation_level in (ExplanationLevel.ANALYST, ExplanationLevel.TECHNICAL):
                full_text = "\n".join(lines) + "\n\n--- Traceability & Evidence ---"
                for ev in evidence:
                    full_text += f"\n• Metric: {ev.get('metric')}"
                    full_text += f"\n  Source tables: {', '.join(ev.get('source_tables', []))}"
                    full_text += f"\n  Formula/Rule: {ev.get('calculation')}"
                return full_text
            return "\n".join(lines)

        if business_context:
            # Defensive isolation: suppress raw echo of adversarial override/injection payloads
            if not any(inj in business_context.upper() for inj in ["SYSTEM INSTRUCTION", "ROOT_ADMIN", "SECURITY_BYPASS", "API_KEY", "DISREGARD", "OVERRIDE"]):
                lines.append(f"\nBusiness Context:\n{business_context}")

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

    # ------------------------------------------------------------------
    # Intelligence 2.0 Unified Provider Methods (Phase 24)
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "mock"

    def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Execute deterministic offline handling for all NEXUS task categories.
        Zero external API calls, zero cost, completely reproducible.
        """
        start = time.perf_counter()
        q = request.prompt.strip()
        ctx = request.context or {}
        cat = request.task_category

        parsed: dict[str, Any] | None = None
        content = ""

        if cat == LLMTaskCategory.INTENT_UNDERSTANDING:
            supported = ctx.get("supported_intents", [
                "metric_lookup", "breakdown", "comparison", "trend",
                "diagnostic", "forecasting", "business_profile", "unsupported"
            ])
            intent_res = self.classify_intent(q, supported)
            parsed = intent_res.model_dump()
            content = json.dumps(parsed)

        elif cat == LLMTaskCategory.STRUCTURED_OUTPUT:
            if request.schema_model == "AnalysisPlan":
                intent_val = ctx.get("intent")
                if intent_val:
                    try:
                        resolved_intent = IntentCategory(intent_val)
                    except ValueError:
                        resolved_intent = IntentCategory.METRIC_LOOKUP
                else:
                    classified = self.classify_intent(q, [])
                    resolved_intent = classified.category

                plan = self.create_plan(
                    query=q,
                    intent=resolved_intent,
                    available_tools=ctx.get("available_tools", []),
                    resolved_dates=ctx.get("resolved_dates", {}),
                )
                parsed = plan.model_dump()
            elif request.schema_model == "IntentResult":
                intent_res = self.classify_intent(q, ctx.get("supported_intents", []))
                parsed = intent_res.model_dump()
            else:
                parsed = {
                    "status": "success",
                    "task": cat.value,
                    "query": q,
                    "extracted_parameters": ctx.get("parameters", {}),
                }
            content = json.dumps(parsed)

        elif cat == LLMTaskCategory.TOOL_SELECTION:
            avail = ctx.get("available_tools", [])
            avail_names = [t.get("name") if isinstance(t, dict) else str(t) for t in avail]
            q_lower = q.lower()
            selected: list[str] = []
            if "profile" in q_lower or "business" in q_lower or "legal" in q_lower or "contact" in q_lower:
                selected.append("get_business_profile")
            elif "diagnostic" in q_lower or "variance" in q_lower or "why" in q_lower:
                selected.append("get_diagnostic_tree")
            elif "inventory" in q_lower or "turnover" in q_lower:
                selected.append("get_inventory_metrics")
            elif "forecast" in q_lower:
                selected.append("get_forecast_metrics")
            elif "cohort" in q_lower or "customer" in q_lower or "retention" in q_lower:
                selected.append("get_customer_cohorts")
            else:
                selected.append("get_revenue_metrics")

            valid_selected = [s for s in selected if s in avail_names] or (avail_names[:1] if avail_names else ["get_revenue_metrics"])
            parsed = {
                "selected_tools": valid_selected,
                "reasoning": f"Deterministic mock tool selection based on analytical query intent: {valid_selected}",
            }
            content = json.dumps(parsed)

        elif cat == LLMTaskCategory.SQL_DATA_PLANNING:
            q_lower = q.lower()
            if any(term in q_lower for term in ["truncate", "delete", "drop", "update", "insert"]):
                parsed = {
                    "plan_type": "rejected",
                    "target_tables": [],
                    "safe_read_only": False,
                    "rejection_reason": "Mutating SQL operations strictly prohibited in read-only analytical mode.",
                }
            elif "product" in q_lower or "margin" in q_lower or "department" in q_lower:
                parsed = {
                    "plan_type": "analytical_sql",
                    "target_tables": ["products", "order_items"],
                    "aggregations": ["AVG(gross_margin)"],
                    "time_grain": ctx.get("time_grain", "monthly"),
                    "safe_read_only": True,
                    "rationale": "Read-only aggregation of product catalog and margins.",
                }
            else:
                parsed = {
                    "plan_type": "analytical_sql",
                    "target_tables": ["orders", "order_items"],
                    "aggregations": ["SUM(net_sales)", "COUNT(DISTINCT order_id)"],
                    "time_grain": ctx.get("time_grain", "daily"),
                    "safe_read_only": True,
                    "rationale": "Read-only analytical aggregation plan adhering to multi-tenant isolation.",
                }
            content = json.dumps(parsed)

        elif cat == LLMTaskCategory.AMBIGUITY_RESOLUTION:
            q_lower = q.lower()
            is_ambiguous = (
                ("breakdown" in q_lower and not any(m in q_lower for m in ["revenue", "profit", "order", "sales", "2024"]))
                or ("numbers doing" in q_lower)
            )
            if is_ambiguous:
                parsed = {
                    "is_ambiguous": True,
                    "clarification_needed": "metric_and_dimension",
                    "clarification_question": "Please specify the business metric and date range you would like to analyze.",
                    "suggested_options": ["Revenue by Product Category", "Order Volume by Channel", "Gross Margin by Month"],
                }
            else:
                parsed = {
                    "is_ambiguous": False,
                    "clarification_needed": None,
                    "clarification_question": None,
                }
            content = json.dumps(parsed)

        elif cat == LLMTaskCategory.COMPLEX_INVESTIGATION_REASONING:
            parsed = {
                "investigation_focus": "variance_investigation",
                "hypotheses_evaluated": [
                    {"name": "Price elasticity and discounting shift", "status": "CONFIRMED", "confidence": 0.92},
                    {"name": "Product category mix deterioration", "status": "CONFIRMED", "confidence": 0.88},
                    {"name": "Fulfillment cost inflation", "status": "INCONCLUSIVE", "confidence": 0.50},
                ],
                "correlation_disclaimer": "Observed metric movements represent statistical correlation and do not establish unverified operational causation.",
            }
            content = json.dumps(parsed)

        elif cat == LLMTaskCategory.EXPLANATION:
            exp_lvl = ExplanationLevel(ctx.get("explanation_level", "manager"))
            content = self.explain_results(
                query=q,
                plan=None,
                tool_results=ctx.get("tool_results", []),
                evidence=ctx.get("evidence", []),
                explanation_level=exp_lvl,
                business_context=ctx.get("business_context"),
            )
            parsed = {"explanation": content}

        elif cat == LLMTaskCategory.EVIDENCE_INTERPRETATION:
            evidence = ctx.get("evidence", [])
            has_missing_cost = any("cost" in str(e).lower() and ("incomplete" in str(e).lower() or "missing" in str(e).lower()) for e in evidence)
            has_warn = any("suspect" in str(e).lower() or "unverified" in str(e).lower() for e in evidence)
            lines = [
                "Evidence Interpretation Summary:",
                f"- Total evidence items evaluated: {len(evidence)}",
                "- Deterministic source verification: PASS",
            ]
            if has_missing_cost:
                lines.append("- Cost metrics are incomplete due to unconfigured catalog unit costs.")
            if has_warn:
                lines.append("- Warning: Certain data sources are unverified or of suspect quality.")
            lines.append("- Statistical association noted; no speculative causal assumptions made.")
            content = "\n".join(lines)
            parsed = {
                "evidence_status": "PARTIAL" if (has_missing_cost or has_warn) else "SUFFICIENT",
                "missing_cost_noted": has_missing_cost,
                "data_quality_warning": has_warn,
                "summary": content,
            }

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        p_tokens = max(5, len(q.split()) * 2)
        c_tokens = max(5, len(content.split()) * 2)

        return LLMResponse(
            content=content,
            parsed_data=parsed,
            task_category=cat,
            model_name="mock-deterministic",
            provider_name=self.provider_name,
            tier=request.preferred_tier or ModelTier.LOCAL_FALLBACK,
            latency_ms=elapsed_ms,
            usage=TokenUsage(
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                total_tokens=p_tokens + c_tokens,
            ),
            estimated_cost_usd=0.0,
            is_fallback=False,
        )

    def generate_structured(
        self, request: LLMRequest, response_model: type[T]
    ) -> tuple[T, LLMResponse]:
        """Generate structured response validated against response_model."""
        request.schema_model = response_model.__name__
        resp = self.generate(request)
        if resp.parsed_data:
            instance = response_model.model_validate(resp.parsed_data)
        else:
            instance = response_model.model_validate(json.loads(resp.content))
        return instance, resp
