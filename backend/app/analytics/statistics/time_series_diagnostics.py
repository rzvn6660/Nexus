"""Deterministic time-series statistical diagnostics: stationarity, autocorrelation, trend, and anomaly detection."""

from typing import List, Dict, Any, Optional
import numpy as np
from scipy import stats
from app.analytics.core.types import TrendDirection
from app.analytics.core.models import TimeSeriesDiagnosticResult
from app.analytics.core.exceptions import InsufficientDataError


class TimeSeriesDiagnosticAnalyzer:
    """
    Computes deterministic statistical diagnostics on sequential time series observations:
    - Augmented Dickey-Fuller (ADF) stationarity testing
    - Autocorrelation Function (ACF) lag evaluation
    - Linear trend slope and hypothesis test
    - Empirical seasonality index
    - Residual-based anomaly and structural shift detection
    """

    @classmethod
    def evaluate(
        cls,
        values: List[float],
        dates: Optional[List[str]] = None,
        metric_name: str = "metric",
        granularity: str = "monthly",
        alpha: float = 0.05,
    ) -> TimeSeriesDiagnosticResult:
        """
        Evaluate full diagnostic battery on time-ordered numeric observations.
        """
        if not values:
            raise InsufficientDataError(f"Cannot diagnose empty time series for {metric_name}.")

        clean_data = []
        for i, v in enumerate(values):
            if v is not None and not np.isnan(v) and not np.isinf(v):
                date_str = dates[i] if dates and i < len(dates) else str(i)
                clean_data.append((i, date_str, float(v)))

        n = len(clean_data)
        if n < 4:
            raise InsufficientDataError(
                f"Time series diagnostics require at least 4 observations, got {n} valid points for {metric_name}."
            )

        indices = np.array([p[0] for p in clean_data], dtype=float)
        date_labels = [p[1] for p in clean_data]
        arr = np.array([p[2] for p in clean_data], dtype=float)

        # 1. Trend Analysis via OLS on time index
        t = np.arange(n, dtype=float)
        t_mean = np.mean(t)
        y_mean = np.mean(arr)
        denom = np.sum((t - t_mean) ** 2)
        slope = float(np.sum((t - t_mean) * (arr - y_mean)) / denom) if denom > 0 else 0.0
        intercept = float(y_mean - slope * t_mean)

        y_pred = intercept + slope * t
        residuals = arr - y_pred
        ssr = float(np.sum(residuals ** 2))
        df_e = n - 2
        se_slope = np.sqrt((ssr / df_e) / denom) if (df_e > 0 and denom > 0 and ssr > 0) else 0.0

        if se_slope > 0:
            t_stat = slope / se_slope
            p_slope = float(2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=df_e)))
        else:
            p_slope = 1.0 if slope == 0 else 0.0

        if p_slope < alpha and abs(slope) > 1e-4:
            trend_dir = TrendDirection.INCREASE if slope > 0 else TrendDirection.DECREASE
        else:
            trend_dir = TrendDirection.UNCHANGED

        # 2. Stationarity Check (Augmented Dickey-Fuller)
        adf_stat: Optional[float] = None
        adf_pval: Optional[float] = None
        is_stationary: bool = False

        if n >= 8:
            try:
                from statsmodels.tsa.stattools import adfuller
                adf_res = adfuller(arr, autolag="AIC")
                adf_stat = float(adf_res[0])
                adf_pval = float(adf_res[1])
                is_stationary = adf_pval < alpha
            except Exception:
                # Fallback: rolling variance and mean equality test
                mid = n // 2
                v1, v2 = np.var(arr[:mid]), np.var(arr[mid:])
                m1, m2 = np.mean(arr[:mid]), np.mean(arr[mid:])
                is_stationary = (abs(m1 - m2) / (np.std(arr) + 1e-8) < 0.5) and (0.5 < (v1 + 1e-8)/(v2 + 1e-8) < 2.0)
        else:
            # Short series variance stability
            mid = n // 2
            m1, m2 = np.mean(arr[:mid]), np.mean(arr[mid:])
            is_stationary = abs(m1 - m2) / (np.std(arr) + 1e-8) < 0.5

        # 3. Autocorrelation Function (ACF) up to lag K
        max_lags = min(10, max(1, n // 3))
        acf_dict: Dict[int, float] = {}
        var_total = np.var(arr)

        if var_total > 0:
            for lag in range(1, max_lags + 1):
                y_t = arr[lag:] - y_mean
                y_t_k = arr[:-lag] - y_mean
                c_k = np.sum(y_t * y_t_k) / n
                r_k = float(c_k / var_total)
                acf_dict[lag] = round(r_k, 4)
        else:
            for lag in range(1, max_lags + 1):
                acf_dict[lag] = 0.0

        # 4. Seasonality Detection
        seasonal_period = None
        if granularity.lower() == "monthly" and n >= 18:
            seasonal_period = 12
        elif granularity.lower() == "weekly" and n >= 14:
            seasonal_period = 4  # approximately monthly cycle
        elif granularity.lower() == "daily" and n >= 21:
            seasonal_period = 7  # day-of-week cycle

        seasonal_strength = 0.0
        if seasonal_period and seasonal_period in acf_dict:
            seasonal_strength = max(0.0, acf_dict[seasonal_period])
        elif acf_dict:
            # Inspect highest positive autocorrelation at lag > 1
            lags_over_1 = {k: v for k, v in acf_dict.items() if k > 1 and v > 0.3}
            if lags_over_1:
                best_lag = max(lags_over_1, key=lags_over_1.get)
                seasonal_period = best_lag
                seasonal_strength = lags_over_1[best_lag]

        # 5. Anomaly Detection on Detrended Residuals (Tukey IQR Fences)
        q25, q75 = np.percentile(residuals, [25, 75])
        iqr_res = q75 - q25
        lower_fence = q25 - 2.0 * iqr_res
        upper_fence = q75 + 2.0 * iqr_res

        anomaly_indices = [int(i) for i in np.where((residuals < lower_fence) | (residuals > upper_fence))[0]]
        anomaly_dates = [date_labels[i] for i in anomaly_indices]

        # Senior-level synthesis interpretation
        trend_desc = f"{trend_dir.value} (slope={slope:+.2f}/period, p={p_slope:.4f})"
        stat_desc = f"stationary (p={adf_pval:.4f})" if is_stationary and adf_pval is not None else (
            "stationary" if is_stationary else f"non-stationary (p={adf_pval:.4f})" if adf_pval is not None else "non-stationary"
        )
        season_desc = f"evidence of {seasonal_period}-period seasonality (strength={seasonal_strength:.2f})" if seasonal_period and seasonal_strength >= 0.3 else "no strong seasonality detected"
        anom_desc = f"{len(anomaly_indices)} anomaly observation(s) identified" if anomaly_indices else "no extreme anomalies detected"

        interp = (
            f"Time series analysis for {metric_name} ({granularity}, n={n}): "
            f"Trend is {trend_desc}; series is {stat_desc}; "
            f"{season_desc}; {anom_desc}."
        )

        limitations = [
            "Linear trend analysis assumes a constant rate of change across the entire observation window.",
            "Short series (n < 20) may yield low statistical power for ADF stationarity tests and seasonal lag identification.",
            "Anomalies represent statistical deviations from linear trend and should be investigated for underlying operational root causes.",
        ]

        return TimeSeriesDiagnosticResult(
            metric=metric_name,
            granularity=granularity,
            sample_size=n,
            trend_slope=round(slope, 4),
            trend_direction=trend_dir,
            trend_p_value=round(p_slope, 6),
            is_stationary=is_stationary,
            adf_statistic=round(adf_stat, 4) if adf_stat is not None else None,
            adf_p_value=round(adf_pval, 6) if adf_pval is not None else None,
            autocorrelations=acf_dict,
            seasonal_period=seasonal_period,
            seasonal_strength=round(float(seasonal_strength), 4),
            anomalies_detected=len(anomaly_indices),
            anomaly_indices=anomaly_indices,
            anomaly_dates=anomaly_dates,
            interpretation=interp,
            limitations=limitations,
        )
