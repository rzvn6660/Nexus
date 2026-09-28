"""Deterministic Pareto 80/20 concentration analysis and Gini inequality metrics."""

from typing import List, Dict, Any, Optional
import numpy as np
from app.analytics.core.models import ParetoAnalysisResult
from app.analytics.core.exceptions import InsufficientDataError


class ParetoAnalyzer:
    """
    Computes deterministic concentration metrics across business distributions:
    - Top 20% contributor share (Pareto 80/20 principle validation)
    - Exact Gini inequality coefficient
    - Lorenz curve coordinates for analytical visualization
    - Entity-level contribution ranking and concentration classification
    """

    @classmethod
    def evaluate(
        cls,
        entities: List[Dict[str, Any]],
        metric_key: str = "revenue",
        entity_id_key: str = "entity_id",
        entity_name_key: str = "entity_name",
        dimension_name: str = "customers",
    ) -> ParetoAnalysisResult:
        """
        Evaluate Pareto concentration on a list of entity records.
        """
        if not entities:
            raise InsufficientDataError(f"Cannot evaluate Pareto concentration on empty list of {dimension_name}.")

        clean_entities = []
        for e in entities:
            raw_val = e.get(metric_key, 0.0)
            if raw_val is not None and not np.isnan(float(raw_val)) and not np.isinf(float(raw_val)):
                val = max(0.0, float(raw_val))
                clean_entities.append({
                    "id": str(e.get(entity_id_key, "")),
                    "name": str(e.get(entity_name_key, e.get(entity_id_key, "Unknown"))),
                    "value": val,
                })

        total_entities = len(clean_entities)
        if total_entities < 2:
            raise InsufficientDataError(
                f"Pareto concentration analysis requires at least 2 entities, got {total_entities} for {dimension_name}."
            )

        # Sort descending by value
        clean_entities.sort(key=lambda x: x["value"], reverse=True)
        values_desc = [x["value"] for x in clean_entities]
        total_metric = float(sum(values_desc))

        if total_metric <= 0:
            raise ValueError(f"Total metric value for {dimension_name} must be greater than zero.")

        # Top 20% calculation
        top_20_count = max(1, int(np.ceil(0.20 * total_entities)))
        top_20_sum = float(sum(values_desc[:top_20_count]))
        top_20_share = round((top_20_sum / total_metric) * 100.0, 2)

        # 80/20 Rule satisfaction: 70% to 90% share
        satisfies_80_20 = 70.0 <= top_20_share <= 90.0

        # Exact Gini coefficient calculation (using ascending values)
        values_asc = np.array(sorted(values_desc), dtype=float)
        n = total_entities
        index = np.arange(1, n + 1)
        gini = float((2.0 * np.sum(index * values_asc)) / (n * np.sum(values_asc)) - (n + 1.0) / n)
        gini = max(0.0, min(1.0, gini))

        # Concentration classification
        if gini >= 0.60 or top_20_share >= 75.0:
            concentration = "high"
        elif gini >= 0.40 or top_20_share >= 60.0:
            concentration = "moderate"
        else:
            concentration = "low"

        # Lorenz curve points (10 percentile increments)
        lorenz_curve: List[Dict[str, float]] = [{"entity_percentile": 0.0, "cumulative_metric_share": 0.0}]
        cumulative_sum = 0.0
        # Calculate from ascending
        cum_shares = np.cumsum(values_asc) / total_metric * 100.0

        for pct in range(10, 101, 10):
            idx = min(n - 1, int(np.round((pct / 100.0) * n)) - 1)
            lorenz_curve.append({
                "entity_percentile": float(pct),
                "cumulative_metric_share": round(float(cum_shares[idx]), 2),
            })

        # Top contributors list with shares
        top_contributors = []
        running_cum = 0.0
        for i, item in enumerate(clean_entities[:min(10, total_entities)]):
            item_share = (item["value"] / total_metric) * 100.0
            running_cum += item_share
            top_contributors.append({
                "rank": i + 1,
                "id": item["id"],
                "name": item["name"],
                "value": round(item["value"], 2),
                "share_pct": round(item_share, 2),
                "cumulative_share_pct": round(running_cum, 2),
            })

        # Senior-level synthesis interpretation
        rule_desc = "conforms closely to the classic 80/20 Pareto rule" if satisfies_80_20 else (
            "exhibits extreme concentration exceeding 80/20" if top_20_share > 90.0 else "is more evenly distributed than the 80/20 rule"
        )
        interp = (
            f"Concentration analysis of {metric_key} across {total_entities} {dimension_name}: "
            f"Top 20% ({top_20_count} entities) account for {top_20_share:.1f}% of total {metric_key}. "
            f"The distribution {rule_desc} with a Gini coefficient of {gini:.3f} ({concentration} concentration)."
        )

        limitations = [
            "Pareto concentration reflects empirical historical distribution and does not predict future account stability.",
            "High concentration indicates key-account revenue dependency; churn of top entities would exert disproportionate business impact.",
            "Calculations exclude zero-revenue accounts if not present in the ingested population.",
        ]

        return ParetoAnalysisResult(
            metric_name=metric_key,
            entity_dimension=dimension_name,
            total_entities=total_entities,
            total_metric_value=round(total_metric, 2),
            top_20_pct_entities_count=top_20_count,
            top_20_pct_metric_value=round(top_20_sum, 2),
            top_20_pct_share=top_20_share,
            satisfies_80_20_rule=satisfies_80_20,
            gini_coefficient=round(gini, 4),
            concentration_classification=concentration,
            lorenz_curve=lorenz_curve,
            top_contributors=top_contributors,
            interpretation=interp,
            limitations=limitations,
        )
