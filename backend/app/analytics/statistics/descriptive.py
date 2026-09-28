"""Descriptive statistical computations for numerical metrics."""

from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from scipy import stats
from pydantic import BaseModel, Field

from app.analytics.core.types import DistributionType, OutlierMethod
from app.analytics.core.models import (
    DescriptiveExtendedStats,
    ConfidenceInterval,
    OutlierResult,
)
from app.analytics.core.exceptions import InsufficientDataError


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
        """Compute baseline statistical summary across numerical list."""
        if not values:
            return None

        arr = np.array(values, dtype=float)
        arr = arr[~np.isnan(arr) & ~np.isinf(arr)]
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

    @classmethod
    def compute_extended(
        cls,
        values: List[float],
        variable_name: str = "metric",
        alpha: float = 0.05,
    ) -> DescriptiveExtendedStats:
        """
        Compute rigorous senior-level descriptive statistics including skewness,
        kurtosis, distribution normality testing, 95% confidence intervals, and dual-method outlier detection.
        """
        if not values:
            raise InsufficientDataError(f"Cannot compute descriptive statistics on empty dataset for {variable_name}.")

        arr = np.array(values, dtype=float)
        arr = arr[~np.isnan(arr) & ~np.isinf(arr)]
        n = len(arr)
        if n < 1:
            raise InsufficientDataError(f"No valid numeric data remaining for {variable_name} after filtering NaNs.")

        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr, ddof=1)) if n > 1 else 0.0
        var_val = float(np.var(arr, ddof=1)) if n > 1 else 0.0
        min_val = float(np.min(arr))
        max_val = float(np.max(arr))

        # Percentiles
        p10, p25, p50, p75, p90, p95, p99 = np.percentile(arr, [10, 25, 50, 75, 90, 95, 99])
        iqr_val = float(p75 - p25)

        # Mode calculation
        try:
            mode_res = stats.mode(arr, keepdims=False)
            mode_val = float(mode_res.mode) if hasattr(mode_res, "mode") else float(mode_res[0])
        except Exception:
            mode_val = None

        # Coefficient of variation (CV = std / mean), guarded against zero and near-zero means
        cv_val = round(abs(std_val / mean_val), 4) if abs(mean_val) > 1e-9 else None

        # Distribution shape classification via unified normality evaluation
        from app.analytics.statistics.normality import evaluate_normality
        norm_res = evaluate_normality(arr, alpha=alpha)
        skew_val = norm_res.skewness
        kurt_val = norm_res.kurtosis
        is_normal = norm_res.is_normal
        norm_p = norm_res.p_value

        if std_val == 0:
            dist_type = DistributionType.UNDEFINED
        elif is_normal or abs(skew_val) < 0.5:
            dist_type = DistributionType.APPROXIMATELY_NORMAL
        elif skew_val >= 0.5:
            dist_type = DistributionType.RIGHT_SKEWED
        elif skew_val <= -0.5:
            dist_type = DistributionType.LEFT_SKEWED
        elif kurt_val > 1.0:
            dist_type = DistributionType.HEAVY_TAILED
        elif kurt_val < -1.0:
            dist_type = DistributionType.LIGHT_TAILED
        else:
            dist_type = DistributionType.APPROXIMATELY_NORMAL

        # 95% Confidence Interval for Mean (Student's t)
        if n > 1 and std_val > 0:
            se = std_val / np.sqrt(n)
            t_crit = float(stats.t.ppf(1 - alpha / 2, df=n - 1))
            moe = t_crit * se
            ci = ConfidenceInterval(
                point_estimate=round(mean_val, 4),
                lower_bound=round(mean_val - moe, 4),
                upper_bound=round(mean_val + moe, 4),
                confidence_level=1.0 - alpha,
                margin_of_error=round(moe, 4),
            )
        else:
            ci = ConfidenceInterval(
                point_estimate=round(mean_val, 4),
                lower_bound=round(mean_val, 4),
                upper_bound=round(mean_val, 4),
                confidence_level=1.0 - alpha,
                margin_of_error=0.0,
            )

        # Tukey IQR Outlier Detection
        lower_fence = float(p25 - 1.5 * iqr_val)
        upper_fence = float(p75 + 1.5 * iqr_val)
        tukey_mask = (arr < lower_fence) | (arr > upper_fence)
        tukey_indices = [int(i) for i in np.where(tukey_mask)[0]]
        tukey_values = [round(float(v), 4) for v in arr[tukey_mask]]
        outliers_tukey = OutlierResult(
            method=OutlierMethod.TUKEY_IQR,
            count=len(tukey_indices),
            percentage=round((len(tukey_indices) / n) * 100, 2),
            lower_fence=round(lower_fence, 4),
            upper_fence=round(upper_fence, 4),
            outlier_indices=tukey_indices,
            outlier_values=tukey_values,
        )

        # Z-Score Outlier Detection (|z| > 3.0)
        if std_val > 0:
            z_scores = np.abs((arr - mean_val) / std_val)
            z_mask = z_scores > 3.0
            z_indices = [int(i) for i in np.where(z_mask)[0]]
            z_values = [round(float(v), 4) for v in arr[z_mask]]
            outliers_zscore = OutlierResult(
                method=OutlierMethod.Z_SCORE,
                count=len(z_indices),
                percentage=round((len(z_indices) / n) * 100, 2),
                lower_fence=round(mean_val - 3 * std_val, 4),
                upper_fence=round(mean_val + 3 * std_val, 4),
                outlier_indices=z_indices,
                outlier_values=z_values,
            )
        else:
            outliers_zscore = OutlierResult(
                method=OutlierMethod.Z_SCORE,
                count=0,
                percentage=0.0,
                lower_fence=round(mean_val, 4),
                upper_fence=round(mean_val, 4),
                outlier_indices=[],
                outlier_values=[],
            )

        return DescriptiveExtendedStats(
            variable_name=variable_name,
            count=n,
            sum=round(float(np.sum(arr)), 4),
            mean=round(mean_val, 4),
            median=round(float(p50), 4),
            mode=round(mode_val, 4) if mode_val is not None else None,
            std_dev=round(std_val, 4),
            variance=round(var_val, 4),
            coefficient_of_variation=cv_val,
            min=round(min_val, 4),
            max=round(max_val, 4),
            range=round(max_val - min_val, 4),
            iqr=round(iqr_val, 4),
            p10=round(float(p10), 4),
            p25=round(float(p25), 4),
            p50=round(float(p50), 4),
            p75=round(float(p75), 4),
            p90=round(float(p90), 4),
            p95=round(float(p95), 4),
            p99=round(float(p99), 4),
            skewness=round(skew_val, 4),
            kurtosis=round(kurt_val, 4),
            distribution_type=dist_type,
            is_normally_distributed=is_normal,
            normality_p_value=round(norm_p, 5) if norm_p is not None else None,
            confidence_interval_95=ci,
            outliers_tukey=outliers_tukey,
            outliers_zscore=outliers_zscore,
        )

    @classmethod
    def compute_weighted(
        cls,
        values: List[float],
        weights: List[float],
        variable_name: str = "metric",
    ) -> Dict[str, float]:
        """Compute weighted mean and weighted standard deviation."""
        if len(values) != len(weights):
            raise ValueError(f"Lengths must match: values has {len(values)}, weights has {len(weights)}.")

        clean_pairs = [
            (v, w) for v, w in zip(values, weights)
            if v is not None and w is not None
            and not np.isnan(v) and not np.isnan(w)
            and not np.isinf(v) and not np.isinf(w)
            and w > 0
        ]
        if not clean_pairs:
            raise InsufficientDataError("No valid positive weight pairs provided for weighted statistics.")

        vals = np.array([p[0] for p in clean_pairs], dtype=float)
        wgts = np.array([p[1] for p in clean_pairs], dtype=float)
        total_wgt = float(np.sum(wgts))

        weighted_mean = float(np.sum(vals * wgts) / total_wgt)
        variance = float(np.sum(wgts * ((vals - weighted_mean) ** 2)) / total_wgt)
        weighted_std = float(np.sqrt(variance))

        return {
            "variable_name": variable_name,
            "weighted_mean": round(weighted_mean, 4),
            "weighted_std": round(weighted_std, 4),
            "weighted_variance": round(variance, 4),
            "total_weight": round(total_wgt, 4),
            "sample_size": len(clean_pairs),
        }

    @classmethod
    def compute_rolling(
        cls,
        values: List[float],
        window_size: int = 7,
    ) -> Dict[str, List[Optional[float]]]:
        """Compute rolling mean, rolling standard deviation, and rolling min/max."""
        if window_size < 1:
            raise ValueError(f"Window size must be >= 1, got {window_size}.")

        series = pd.Series(values, dtype=float)
        roll = series.rolling(window=window_size, min_periods=1)

        rolling_mean = [None if np.isnan(x) else round(float(x), 4) for x in roll.mean()]
        rolling_std = [None if np.isnan(x) else round(float(x), 4) for x in roll.std(ddof=1)]
        rolling_min = [None if np.isnan(x) else round(float(x), 4) for x in roll.min()]
        rolling_max = [None if np.isnan(x) else round(float(x), 4) for x in roll.max()]

        return {
            "rolling_mean": rolling_mean,
            "rolling_std": rolling_std,
            "rolling_min": rolling_min,
            "rolling_max": rolling_max,
        }

    @classmethod
    def compute_growth_metrics(
        cls,
        values: List[float],
        periods_per_year: int = 12,
    ) -> Dict[str, Any]:
        """Compute period-over-period growth rates, cumulative growth, and CAGR."""
        clean_vals = [float(v) for v in values if v is not None and not np.isnan(v) and not np.isinf(v)]
        if len(clean_vals) < 2:
            raise InsufficientDataError(f"Growth calculation requires at least 2 points, got {len(clean_vals)}.")

        first_val = clean_vals[0]
        last_val = clean_vals[-1]
        absolute_change = last_val - first_val
        pct_change = ((last_val - first_val) / abs(first_val)) * 100.0 if first_val != 0 else None

        # Period-by-period growth
        period_growths: List[Optional[float]] = [None]
        for i in range(1, len(clean_vals)):
            prev = clean_vals[i - 1]
            curr = clean_vals[i]
            if prev != 0:
                period_growths.append(round(((curr - prev) / abs(prev)) * 100.0, 2))
            else:
                period_growths.append(None)

        # CAGR calculation: (last / first) ** (1 / years) - 1
        num_periods = len(clean_vals) - 1
        years = num_periods / float(periods_per_year)
        cagr: Optional[float] = None
        if first_val > 0 and last_val > 0 and years > 0:
            cagr = round((((last_val / first_val) ** (1.0 / years)) - 1.0) * 100.0, 2)

        return {
            "start_value": round(first_val, 4),
            "end_value": round(last_val, 4),
            "absolute_change": round(absolute_change, 4),
            "percentage_change": round(pct_change, 2) if pct_change is not None else None,
            "cagr_pct": cagr,
            "period_growths_pct": period_growths,
            "num_periods": num_periods,
        }
