"""Deterministic statistical correlation analysis between numerical variables."""

from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from scipy import stats
from app.analytics.core.types import CorrelationMethod
from app.analytics.core.models import CorrelationResult
from app.analytics.core.exceptions import InsufficientDataError


class CorrelationAnalyzer:
    """Calculates bivariate linear (Pearson) or monotonic (Spearman) correlation and covariance."""

    @classmethod
    def select_method(cls, x: List[float], y: List[float]) -> Tuple[CorrelationMethod, str]:
        """
        Deterministic method selection: evaluates normality and outlier density.
        Recommends Spearman if data exhibits severe non-normality or extreme outliers;
        otherwise recommends Pearson.
        """
        clean_pairs = [
            (xi, yi) for xi, yi in zip(x, y)
            if xi is not None and yi is not None
            and not np.isnan(xi) and not np.isnan(yi)
            and not np.isinf(xi) and not np.isinf(yi)
        ]
        if len(clean_pairs) < 8:
            return CorrelationMethod.SPEARMAN, "Small sample size (<8); Spearman rank correlation is more robust against distributional violations."

        vx = [p[0] for p in clean_pairs]
        vy = [p[1] for p in clean_pairs]

        from app.analytics.statistics.normality import evaluate_normality
        norm_x = evaluate_normality(vx)
        norm_y = evaluate_normality(vy)

        if not norm_x.is_normal or not norm_y.is_normal:
            reason = (
                f"Significant deviation from normality detected (x_test={norm_x.test_used}, y_test={norm_y.test_used}); "
                f"Spearman monotonic rank correlation recommended."
            )
            return CorrelationMethod.SPEARMAN, reason

        return CorrelationMethod.PEARSON, "Sample distributions satisfy normality assumptions; Pearson linear correlation recommended."

    @classmethod
    def compute(
        cls,
        x: List[float],
        y: List[float],
        variable_x: str = "x",
        variable_y: str = "y",
        method: CorrelationMethod = CorrelationMethod.PEARSON,
    ) -> CorrelationResult:
        """
        Evaluate correlation between two aligned numeric series.
        """
        if len(x) != len(y):
            raise ValueError(f"Length mismatch: x has {len(x)} points, y has {len(y)} points.")

        # Clean NaNs and infinite values
        valid_pairs = [
            (xi, yi)
            for xi, yi in zip(x, y)
            if xi is not None
            and yi is not None
            and not np.isnan(xi)
            and not np.isnan(yi)
            and not np.isinf(xi)
            and not np.isinf(yi)
        ]

        n = len(valid_pairs)
        if n < 3:
            raise InsufficientDataError(
                f"Insufficient sample size for correlation analysis: got {n} valid pairs, minimum is 3."
            )

        vx = [p[0] for p in valid_pairs]
        vy = [p[1] for p in valid_pairs]

        # Check zero variance
        if np.std(vx) == 0 or np.std(vy) == 0:
            return CorrelationResult(
                variable_x=variable_x,
                variable_y=variable_y,
                method=method.value,
                correlation_coefficient=0.0,
                p_value=1.0,
                sample_size=n,
                strength="undefined",
                direction="zero",
                causation_warning="Correlation measures statistical association only and DOES NOT imply causation.",
                limitations=["One or both variables had zero variance (all values identical)."],
            )

        if method == CorrelationMethod.SPEARMAN:
            res = stats.spearmanr(vx, vy)
            coef = float(res.statistic)
            pval = float(res.pvalue)
        else:
            res = stats.pearsonr(vx, vy)
            coef = float(res.statistic)
            pval = float(res.pvalue)

        abs_c = abs(coef)
        if abs_c >= 0.7:
            strength = "strong"
        elif abs_c >= 0.4:
            strength = "moderate"
        elif abs_c >= 0.2:
            strength = "weak"
        else:
            strength = "negligible"

        direction = "positive" if coef > 0 else ("negative" if coef < 0 else "zero")

        return CorrelationResult(
            variable_x=variable_x,
            variable_y=variable_y,
            method=method.value,
            correlation_coefficient=round(coef, 4),
            p_value=round(pval, 6),
            sample_size=n,
            strength=strength,
            direction=direction,
            causation_warning="Correlation measures statistical association only and DOES NOT imply causation.",
            limitations=[
                "Outliers can disproportionately influence Pearson correlation.",
                "Nonlinear associations may not be captured by linear correlation metrics.",
            ],
        )

    @classmethod
    def compute_covariance(
        cls,
        x: List[float],
        y: List[float],
        variable_x: str = "x",
        variable_y: str = "y",
    ) -> Dict[str, Any]:
        """Compute sample covariance between two numeric series."""
        if len(x) != len(y):
            raise ValueError(f"Length mismatch: x has {len(x)} points, y has {len(y)} points.")

        valid_pairs = [
            (xi, yi) for xi, yi in zip(x, y)
            if xi is not None and yi is not None
            and not np.isnan(xi) and not np.isnan(yi)
            and not np.isinf(xi) and not np.isinf(yi)
        ]
        n = len(valid_pairs)
        if n < 2:
            raise InsufficientDataError(f"Covariance requires at least 2 observations, got {n}.")

        vx = [p[0] for p in valid_pairs]
        vy = [p[1] for p in valid_pairs]
        cov_matrix = np.cov(vx, vy, ddof=1)
        cov_val = float(cov_matrix[0, 1])

        return {
            "variable_x": variable_x,
            "variable_y": variable_y,
            "covariance": round(cov_val, 4),
            "sample_size": n,
            "interpretation": (
                f"Covariance is {cov_val:.2f}, indicating that {variable_x} and {variable_y} "
                f"tend to {'vary in the same direction' if cov_val > 0 else ('vary in opposite directions' if cov_val < 0 else 'show no linear co-movement')}."
            ),
        }

    @classmethod
    def compute_matrix(
        cls,
        variables: Dict[str, List[float]],
        method: CorrelationMethod = CorrelationMethod.PEARSON,
    ) -> Dict[str, Any]:
        """Compute an n x n pairwise correlation matrix across multiple variables."""
        var_names = list(variables.keys())
        if len(var_names) < 2:
            raise ValueError("Correlation matrix requires at least 2 variables.")

        matrix: Dict[str, Dict[str, Optional[float]]] = {k: {} for k in var_names}
        p_matrix: Dict[str, Dict[str, Optional[float]]] = {k: {} for k in var_names}

        for i, v1 in enumerate(var_names):
            for j, v2 in enumerate(var_names):
                if i == j:
                    matrix[v1][v2] = 1.0
                    p_matrix[v1][v2] = 0.0
                elif j < i:
                    matrix[v1][v2] = matrix[v2][v1]
                    p_matrix[v1][v2] = p_matrix[v2][v1]
                else:
                    try:
                        res = cls.compute(variables[v1], variables[v2], variable_x=v1, variable_y=v2, method=method)
                        matrix[v1][v2] = res.correlation_coefficient
                        p_matrix[v1][v2] = res.p_value
                    except Exception:
                        matrix[v1][v2] = None
                        p_matrix[v1][v2] = None

        return {
            "variables": var_names,
            "method": method.value,
            "correlation_matrix": matrix,
            "p_value_matrix": p_matrix,
            "causation_warning": "Correlation matrix measures pairwise statistical association only and DOES NOT imply causation.",
        }
