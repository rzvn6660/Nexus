"""NEXUS Decision Gateway Domain-Tuning Exemplars (Phase 13 Taxonomy Reconciled).

Version: 1.1.0 (Auditable, Deterministic, Bounded, Canonical Taxonomy Aligned)
Purpose: Provides calibrated disambiguation guidance for discrete decision tasks (such as
Intent Routing and Tool Selection) within the Decision Gateway subsystem.

LEAKAGE PREVENTION GUARANTEE:
All exemplars below are strictly held-out from the 57 evaluation benchmark cases.
They feature distinct terminology, fictional business scenarios (e.g. cloud SaaS,
freight logistics, semiconductor manufacturing), and zero overlap with test set questions.
"""

from typing import Any

from app.decisions.taxonomy import CanonicalIntent

# Version identifier for audit trails
EXEMPLAR_SET_VERSION = "1.1.0"

# Bounded, explicit intent disambiguation exemplars targeting Phase 12B/12C error patterns
NEXUS_INTENT_EXEMPLARS: list[dict[str, Any]] = [
    # -------------------------------------------------------------------------
    # 1. Compound Revenue + Variance Queries
    # Pattern: Questions seeking causal drivers, delta explanations, or decompositions.
    # Disambiguation: Must route to 'diagnostic_analysis', not 'metric_lookup'.
    # -------------------------------------------------------------------------
    {
        "exemplar_id": "EX-INT-001",
        "pattern_type": "compound_variance",
        "query": "Explain the variance in regional cloud subscription revenue between Q1 and Q2",
        "target_intent": CanonicalIntent.DIAGNOSTIC_ANALYSIS.value,
        "target_subtype": "variance_decomposition",
        "rationale": "Inquiring about variance explanations requires diagnostic causal decomposition, not a single point lookup.",
    },
    {
        "exemplar_id": "EX-INT-002",
        "pattern_type": "compound_variance",
        "query": "Decompose the EBITDA change into volume and rate effects for fiscal year 2023",
        "target_intent": CanonicalIntent.DIAGNOSTIC_ANALYSIS.value,
        "target_subtype": "price_volume_mix",
        "rationale": "Price-volume-mix or driver decomposition queries belong strictly to diagnostic analysis.",
    },

    # -------------------------------------------------------------------------
    # 2. Breakdown + Metric Queries
    # Pattern: Questions partitioning a metric across non-temporal dimensions.
    # Disambiguation: Must route to 'product_analysis' or 'expense_analysis'.
    # -------------------------------------------------------------------------
    {
        "exemplar_id": "EX-INT-003",
        "pattern_type": "breakdown_metric",
        "query": "Break down quarterly software license renewals grouped by geographic sales territory",
        "target_intent": CanonicalIntent.PRODUCT_ANALYSIS.value,
        "target_subtype": "category_breakdown",
        "rationale": "Partitioning or grouping a metric by qualitative business attributes or geography is a product/dimensional breakdown.",
    },
    {
        "exemplar_id": "EX-INT-004",
        "pattern_type": "breakdown_metric",
        "query": "Show distribution of infrastructure hosting expenses categorized by cloud provider tier",
        "target_intent": CanonicalIntent.EXPENSE_ANALYSIS.value,
        "target_subtype": "category_breakdown",
        "rationale": "Aggregating expense distributions by vendor tier constitutes a categorical expense breakdown.",
    },

    # -------------------------------------------------------------------------
    # 3. Date + Metric + Dimension Queries
    # Pattern: Single point in time or historical aggregate with attribute filter.
    # Disambiguation: Must route to 'metric_lookup', not 'comparison'.
    # -------------------------------------------------------------------------
    {
        "exemplar_id": "EX-INT-005",
        "pattern_type": "date_metric_dimension",
        "query": "What was the total invoice volume processed in the European sector for October 2023?",
        "target_intent": CanonicalIntent.METRIC_LOOKUP.value,
        "target_subtype": "single_metric",
        "rationale": "A single historical count/volume with temporal and regional filters without delta calculations is a metric lookup.",
    },
    {
        "exemplar_id": "EX-INT-006",
        "pattern_type": "date_metric_dimension",
        "query": "Retrieve total raw material procurement cost for calendar year 2022",
        "target_intent": CanonicalIntent.METRIC_LOOKUP.value,
        "target_subtype": "single_metric",
        "rationale": "Querying a single cumulative total over a calendar boundary is an unambiguous metric lookup.",
    },

    # -------------------------------------------------------------------------
    # 4. Ambiguous Analytical Requests (Comparison vs Trend vs Ranking)
    # Pattern: Tracking performance against baselines or comparative benchmarks.
    # Disambiguation: Must route to 'comparison' or 'product_analysis'.
    # -------------------------------------------------------------------------
    {
        "exemplar_id": "EX-INT-007",
        "pattern_type": "ambiguous_comparison",
        "query": "How did outbound logistics freight costs track against the budget target during Q3?",
        "target_intent": CanonicalIntent.COMPARISON.value,
        "target_subtype": "period_comparison",
        "rationale": "Tracking actuals against a budget baseline or prior timeline constitutes comparative analysis.",
    },
    {
        "exemplar_id": "EX-INT-008",
        "pattern_type": "ambiguous_comparison",
        "query": "Compare operating margin performance of division Alpha versus division Beta",
        "target_intent": CanonicalIntent.COMPARISON.value,
        "target_subtype": "product_comparison",
        "rationale": "Cross-entity or cross-product performance comparison maps to comparison.",
    },
    {
        "exemplar_id": "EX-INT-009",
        "pattern_type": "ranking_lookup",
        "query": "Which enterprise software tier produced the highest contracted ARR during Q4?",
        "target_intent": CanonicalIntent.PRODUCT_ANALYSIS.value,
        "target_subtype": "ranking_lookup",
        "rationale": "Identifying the single top/highest performing item from an entity pool is a product analysis ranking lookup.",
    },

    # -------------------------------------------------------------------------
    # 5. Queries Where Multiple Intents Appear Related
    # Pattern: Statistical correlation vs Forecasting vs Semantic vs Unsupported.
    # Disambiguation: Clear boundaries between predictive, relational, and non-BI.
    # -------------------------------------------------------------------------
    {
        "exemplar_id": "EX-INT-010",
        "pattern_type": "multitask_disambiguation",
        "query": "Is there a statistically significant correlation between partner discount rates and deal cycle length?",
        "target_intent": CanonicalIntent.STATISTICAL_ANALYSIS.value,
        "target_subtype": "correlation",
        "rationale": "Evaluating statistical dependence between two continuous variables is statistical analysis.",
    },
    {
        "exemplar_id": "EX-INT-011",
        "pattern_type": "multitask_disambiguation",
        "query": "Project warehouse capacity utilization rates for the subsequent 90 days",
        "target_intent": CanonicalIntent.FORECASTING.value,
        "target_subtype": "forecast_lookup",
        "rationale": "Forward-looking numerical estimation over future temporal horizons maps to forecasting.",
    },
    {
        "exemplar_id": "EX-INT-012",
        "pattern_type": "multitask_disambiguation",
        "query": "Define what our internal metric CAC stands for in customer success manuals",
        "target_intent": CanonicalIntent.SEMANTIC_RESOLUTION.value,
        "target_subtype": "semantic_resolution",
        "rationale": "Inquiries regarding business definitions, acronyms, or formula documentation map to semantic resolution.",
    },
    {
        "exemplar_id": "EX-INT-013",
        "pattern_type": "multitask_disambiguation",
        "query": "Draft a motivational keynote speech for the upcoming executive summit",
        "target_intent": CanonicalIntent.UNSUPPORTED.value,
        "target_subtype": "unsupported",
        "rationale": "Creative generative writing and non-BI operational tasks are strictly unsupported.",
    },
    {
        "exemplar_id": "EX-INT-014",
        "pattern_type": "operational_domain",
        "query": "Which supply warehouse has stock levels below minimum safety replenishment thresholds?",
        "target_intent": CanonicalIntent.INVENTORY_ANALYSIS.value,
        "target_subtype": "inventory_lookup",
        "rationale": "Inquiries into physical stock, safety margins, and replenishment triggers map to inventory analysis.",
    },
    {
        "exemplar_id": "EX-INT-015",
        "pattern_type": "operational_domain",
        "query": "What is the historical logo retention percentage for enterprise cohort 2021?",
        "target_intent": CanonicalIntent.CUSTOMER_ANALYSIS.value,
        "target_subtype": "customer_lookup",
        "rationale": "Cohort retention, customer lifetime value, and segmentation map to customer analysis.",
    },
]


def get_intent_exemplars() -> list[dict[str, Any]]:
    """Return an immutable copy of the versioned intent exemplar set."""
    return [dict(e) for e in NEXUS_INTENT_EXEMPLARS]


def format_exemplars_for_prompt() -> str:
    """Format exemplars as a concise prompt string for LLM or System-1 contextual states."""
    lines = [f"# NEXUS Intent Disambiguation Guidelines (v{EXEMPLAR_SET_VERSION})"]
    for ex in NEXUS_INTENT_EXEMPLARS:
        lines.append(
            f"- Query: \"{ex['query']}\" -> Intent: {ex['target_intent']} "
            f"(Subtype: {ex.get('target_subtype', 'none')}) [{ex['rationale']}]"
        )
    return "\n".join(lines)


def verify_zero_evaluation_leakage(evaluation_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Programmatically verify that zero evaluation questions leaked into the exemplar set.
    Checks exact matches, lowercased matches, and high token overlap.
    """
    leakage_detected = []

    for ex in NEXUS_INTENT_EXEMPLARS:
        ex_text = ex["query"].strip().lower()
        ex_tokens = set(ex_text.split())

        for case in evaluation_cases:
            case_id = case.get("id", "UNKNOWN")
            case_text = case.get("question", "").strip().lower()
            if not case_text:
                continue

            # Exact match check
            if ex_text == case_text:
                leakage_detected.append({
                    "exemplar_id": ex["exemplar_id"],
                    "case_id": case_id,
                    "reason": "Exact string match",
                })
                continue

            # High Jaccard token similarity check (> 0.70)
            case_tokens = set(case_text.split())
            intersection = ex_tokens.intersection(case_tokens)
            union = ex_tokens.union(case_tokens)
            similarity = len(intersection) / len(union) if union else 0.0

            if similarity > 0.70:
                leakage_detected.append({
                    "exemplar_id": ex["exemplar_id"],
                    "case_id": case_id,
                    "similarity": round(similarity, 3),
                    "reason": "Excessive token overlap (>0.70)",
                })

    return {
        "verified_clean": len(leakage_detected) == 0,
        "total_exemplars_checked": len(NEXUS_INTENT_EXEMPLARS),
        "total_test_cases_checked": len(evaluation_cases),
        "violations": leakage_detected,
    }
