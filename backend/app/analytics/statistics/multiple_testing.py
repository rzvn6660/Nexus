"""Deterministic multiple testing corrections for family-wise error rate and false discovery rate."""

from typing import List, Optional
from pydantic import BaseModel, Field
import numpy as np


class MultipleTestingResult(BaseModel):
    """Result of deterministic multiple hypothesis testing correction."""
    method: str = Field(description="Correction method: 'holm', 'benjamini_hochberg', or 'bonferroni'")
    raw_p_values: List[float] = Field(description="Original unadjusted p-values")
    adjusted_p_values: List[float] = Field(description="P-values adjusted for multiple comparisons")
    rejected: List[bool] = Field(description="True if hypothesis is rejected at specified alpha")
    alpha: float = 0.05
    family_wise_error_rate_controlled: bool
    false_discovery_rate_controlled: bool
    num_hypotheses: int
    num_rejected: int
    interpretation: str


class MultipleTestingCorrector:
    """
    Deterministic corrections for multiple hypothesis comparisons.
    Prevents false positives (Type I error inflation) when testing multiple groups or metrics.
    """

    SUPPORTED_METHODS = {"holm", "benjamini_hochberg", "fdr", "bonferroni"}

    @classmethod
    def adjust_p_values(
        cls,
        p_values: List[float],
        method: str = "holm",
        alpha: float = 0.05,
    ) -> MultipleTestingResult:
        """
        Adjust a list of p-values to control FWER or FDR.

        Args:
            p_values: List of raw p-values [0, 1]
            method: 'holm' (Holm-Bonferroni step-down, controls FWER),
                    'benjamini_hochberg' or 'fdr' (controls FDR),
                    'bonferroni' (conservative single-step, controls FWER)
            alpha: Significance threshold (default 0.05)
        """
        method_clean = method.lower().strip()
        if method_clean not in cls.SUPPORTED_METHODS:
            raise ValueError(
                f"Unsupported correction method '{method}'. Supported: {sorted(list(cls.SUPPORTED_METHODS))}"
            )

        m = len(p_values)
        if m == 0:
            return MultipleTestingResult(
                method=method_clean,
                raw_p_values=[],
                adjusted_p_values=[],
                rejected=[],
                alpha=alpha,
                family_wise_error_rate_controlled=True,
                false_discovery_rate_controlled=True,
                num_hypotheses=0,
                num_rejected=0,
                interpretation="No hypotheses provided for testing.",
            )

        # Validate p-values
        cleaned_p = []
        for p in p_values:
            val = float(p)
            val = max(0.0, min(1.0, val))
            cleaned_p.append(val)

        p_arr = np.array(cleaned_p, dtype=float)
        adj_p = np.zeros(m, dtype=float)

        if method_clean == "bonferroni":
            adj_p = np.minimum(1.0, p_arr * m)
            fwer = True
            fdr = False

        elif method_clean == "holm":
            # Holm-Bonferroni step-down
            sort_indices = np.argsort(p_arr)
            sorted_p = p_arr[sort_indices]

            # Step-down adjustments: (m - i) * p_(i+1)
            factors = np.arange(m, 0, -1)
            raw_adj = sorted_p * factors

            # Enforce monotonicity: adj_p[i] = max(adj_p[i], adj_p[i-1])
            cummax_adj = np.maximum.accumulate(raw_adj)
            cummax_adj = np.minimum(1.0, cummax_adj)

            # Unsort back to original ordering
            adj_p[sort_indices] = cummax_adj
            fwer = True
            fdr = False

        elif method_clean in ("benjamini_hochberg", "fdr"):
            # Benjamini-Hochberg step-up for False Discovery Rate
            sort_indices = np.argsort(p_arr)
            sorted_p = p_arr[sort_indices]

            # Step-up adjustments: (m / rank) * p_(rank)
            ranks = np.arange(1, m + 1)
            raw_adj = sorted_p * (m / ranks)

            # Enforce reverse monotonicity: adj_p[i] = min(adj_p[i], adj_p[i+1])
            # Process in reverse from m-1 down to 0
            cur_min = 1.0
            cummin_adj = np.zeros(m, dtype=float)
            for i in range(m - 1, -1, -1):
                cur_min = min(cur_min, raw_adj[i])
                cummin_adj[i] = cur_min
            cummin_adj = np.maximum(0.0, np.minimum(1.0, cummin_adj))

            # Unsort back to original ordering
            adj_p[sort_indices] = cummin_adj
            fwer = False
            fdr = True

        adj_list = [round(float(p), 6) for p in adj_p]
        rejected_list = [bool(p < alpha) for p in adj_p]
        num_rejected = sum(rejected_list)

        interp = (
            f"{method_clean.upper()} multiple-comparison correction across {m} hypotheses at alpha={alpha}: "
            f"{num_rejected} of {m} tests remain statistically significant after adjusting for multiplicity."
        )

        return MultipleTestingResult(
            method=method_clean,
            raw_p_values=cleaned_p,
            adjusted_p_values=adj_list,
            rejected=rejected_list,
            alpha=alpha,
            family_wise_error_rate_controlled=fwer,
            false_discovery_rate_controlled=fdr,
            num_hypotheses=m,
            num_rejected=num_rejected,
            interpretation=interp,
        )
