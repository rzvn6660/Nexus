"""Unified normality evaluation utility for deterministic statistical analytics."""

from dataclasses import dataclass
from typing import Sequence, Optional
import numpy as np
from scipy import stats


@dataclass(frozen=True)
class NormalityEvaluation:
    """Standardized result of distributional normality evaluation."""
    is_normal: bool
    p_value: Optional[float]
    test_used: str
    skewness: float
    kurtosis: float
    sample_size: int
    warning: Optional[str] = None


def evaluate_normality(
    data: Sequence[float],
    alpha: float = 0.05,
) -> NormalityEvaluation:
    """
    Deterministically evaluate sample normality across sample sizes.

    Rules:
    - n < 3: Insufficient sample size for formal normality testing.
    - Zero variance: Degenerate distribution; cannot be normally distributed.
    - 3 <= n <= 5000: Shapiro-Wilk test (most powerful omnibus normality test).
    - n > 5000: D'Agostino's K^2 omnibus test (skewness + kurtosis based).
    - Severe skewness (|skew| > 1.5) or heavy tails (|kurtosis| > 3.0) flag non-normality
      regardless of marginal p-values.
    """
    arr = np.array(data, dtype=float)
    arr = arr[~np.isnan(arr) & ~np.isinf(arr)]
    n = len(arr)

    if n < 3:
        return NormalityEvaluation(
            is_normal=False,
            p_value=None,
            test_used="insufficient_sample",
            skewness=0.0,
            kurtosis=0.0,
            sample_size=n,
            warning=f"Sample size (n={n}) is too small for statistical normality testing (minimum 3 required).",
        )

    var_val = float(np.var(arr, ddof=1)) if n > 1 else 0.0
    if var_val == 0.0:
        return NormalityEvaluation(
            is_normal=False,
            p_value=None,
            test_used="zero_variance",
            skewness=0.0,
            kurtosis=0.0,
            sample_size=n,
            warning="Sample exhibits zero variance (all values identical); distribution is degenerate.",
        )

    # Compute Fisher-Pearson skewness and excess kurtosis
    skew_val = float(stats.skew(arr, bias=False))
    kurt_val = float(stats.kurtosis(arr, bias=False))

    # Select appropriate test based on sample size
    if n <= 5000:
        test_used = "shapiro_wilk"
        try:
            stat_val, p_val = stats.shapiro(arr)
            p_val = float(p_val)
        except Exception:
            p_val = None
    else:
        test_used = "dagostino_k2"
        try:
            stat_val, p_val = stats.normaltest(arr)
            p_val = float(p_val)
        except Exception:
            p_val = None

    if p_val is not None:
        # Standard hypothesis check
        is_normal = p_val >= alpha
        # Guardrail: extreme skew or heavy tails invalidate normality assumption
        if abs(skew_val) > 1.5 or abs(kurt_val) > 3.0:
            is_normal = False
            warning = f"Severe distribution shape anomaly (skewness={skew_val:.2f}, kurtosis={kurt_val:.2f}); normality rejected."
        else:
            warning = None if is_normal else f"Distribution significantly deviates from normality (p={p_val:.4f} < {alpha})."
    else:
        is_normal = False
        warning = "Normality test calculation could not be completed."

    return NormalityEvaluation(
        is_normal=is_normal,
        p_value=round(p_val, 6) if p_val is not None else None,
        test_used=test_used,
        skewness=round(skew_val, 4),
        kurtosis=round(kurt_val, 4),
        sample_size=n,
        warning=warning,
    )
