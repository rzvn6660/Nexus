"""Descriptive statistical computations for numerical metrics."""

from typing import List, Dict, Any, Optional
import numpy as np
from pydantic import BaseModel, Field


class DescriptiveStatsResult(BaseModel):
    """Parametric and non-parametric summary statistics for a numeric variable."""
    variable_name: str
    count: int
    sum: float
    mean: float
    median: float
    std_dev: float
    variance: float
    min: float
    max: float
    range: float
    iqr: float
    p25: float
    p75: float
    p90: float
    p95: float
    p99: float


class DescriptiveStatistics:
    """Computes distribution statistics over numeric collections."""

    @classmethod
    def compute(cls, values: List[float], variable_name: str = "metric") -> Optional[DescriptiveStatsResult]:
        """Compute statistical summary across numerical list."""
        if not values:
            return None

        arr = np.array(values, dtype=float)
        arr = arr[~np.isnan(arr)]
        n = len(arr)
        if n == 0:
            return None

        p25, p50, p75, p90, p95, p99 = np.percentile(arr, [25, 50, 75, 90, 95, 99])
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr, ddof=1)) if n > 1 else 0.0
        var_val = float(np.var(arr, ddof=1)) if n > 1 else 0.0
        min_val = float(np.min(arr))
        max_val = float(np.max(arr))

        return DescriptiveStatsResult(
            variable_name=variable_name,
            count=n,
            sum=round(float(np.sum(arr)), 4),
            mean=round(mean_val, 4),
            median=round(float(p50), 4),
            std_dev=round(std_val, 4),
            variance=round(var_val, 4),
            min=round(min_val, 4),
            max=round(max_val, 4),
            range=round(max_val - min_val, 4),
            iqr=round(float(p75 - p25), 4),
            p25=round(float(p25), 4),
            p75=round(float(p75), 4),
            p90=round(float(p90), 4),
            p95=round(float(p95), 4),
            p99=round(float(p99), 4),
        )
