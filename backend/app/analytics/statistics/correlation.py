"""Deterministic statistical correlation analysis between numerical variables."""

from typing import List, Optional
import numpy as np
from scipy import stats
from app.analytics.core.types import CorrelationMethod
from app.analytics.core.models import CorrelationResult
from app.analytics.core.exceptions import InsufficientDataError


class CorrelationAnalyzer:
    """Calculates bivariate linear (Pearson) or monotonic (Spearman) correlation."""

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
