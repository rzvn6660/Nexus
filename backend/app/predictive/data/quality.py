"""Data quality gate and pre-training validation for historical time series."""

import numpy as np
import pandas as pd

from app.predictive.schemas import DataQualityStatus, ForecastDataQuality


class QualityGateResult(tuple):
    """Result tuple (ForecastDataQuality, is_ready) with attribute delegation to ForecastDataQuality."""
    def __new__(cls, quality: ForecastDataQuality, is_ready: bool):
        return super().__new__(cls, (quality, is_ready))

    @property
    def status(self) -> DataQualityStatus:
        return self[0].status

    @property
    def observation_count(self) -> int:
        return self[0].observation_count

    @property
    def frequency(self) -> str:
        return self[0].frequency

    @property
    def date_from(self) -> str | None:
        return self[0].date_from

    @property
    def date_to(self) -> str | None:
        return self[0].date_to

    @property
    def missing_values(self) -> int:
        return self[0].missing_values

    @property
    def zero_periods_count(self) -> int:
        return self[0].zero_periods_count

    @property
    def outliers_detected(self) -> int:
        return self[0].outliers_detected

    @property
    def warnings(self) -> list[str]:
        return self[0].warnings

    @property
    def blocking_reasons(self) -> list[str]:
        return self[0].blocking_reasons

    @property
    def is_ready(self) -> bool:
        return bool(self[1])


class TimeSeriesQualityGate:
    """
    Evaluates whether an extracted historical time series possesses sufficient
    volume, variance, and continuity to support reliable forecasting models.
    """

    @classmethod
    def evaluate(
        cls,
        df: pd.DataFrame,
        frequency: str,
        min_observations: int = 4,
        date_col: str = "date",
        value_col: str = "value",
    ) -> QualityGateResult:
        """
        Evaluate time series data quality.
        Returns:
            QualityGateResult tuple of (ForecastDataQuality, is_ready_to_forecast: bool)
        """
        obs_count = len(df)
        warnings: list[str] = []
        blocking: list[str] = []

        if obs_count == 0 or df.empty:
            quality = ForecastDataQuality(
                status=DataQualityStatus.INSUFFICIENT_DATA,
                observation_count=0,
                frequency=frequency,
                blocking_reasons=["Insufficient historical data: time series contains zero historical observations."],
            )
            return QualityGateResult(quality, False)

        # Sort and inspect dates
        if date_col not in df.columns:
            if isinstance(df.index, pd.DatetimeIndex):
                df_sorted = df.copy()
                df_sorted[date_col] = df.index
            elif "period_start" in df.columns:
                df_sorted = df.copy()
                df_sorted[date_col] = pd.to_datetime(df["period_start"])
            else:
                df_sorted = df.reset_index().rename(columns={"index": date_col})
        else:
            df_sorted = df.sort_values(date_col).copy()

        first_date = str(df_sorted[date_col].iloc[0])[:10]
        last_date = str(df_sorted[date_col].iloc[-1])[:10]

        # 1. Minimum Observation Check
        if obs_count < min_observations:
            blocking.append(
                f"Insufficient historical observations: series contains only {obs_count} observations. "
                f"Minimum required for {frequency} forecasting is {min_observations}."
            )

        # 2. Duplicate timestamp check
        duplicates = df_sorted.duplicated(subset=[date_col]).sum()
        if duplicates > 0:
            warnings.append(f"Identified {duplicates} duplicate timestamps (aggregated).")

        # 3. Missing values check
        missing_vals = int(df_sorted[value_col].isna().sum())
        if missing_vals > 0:
            blocking.append(f"Series contains {missing_vals} unhandled NaN or Null target values.")

        values = df_sorted[value_col].fillna(0.0).to_numpy(dtype=np.float64)

        # 4. Zero activity periods
        zero_count = int(np.sum(values == 0.0))
        if zero_count > (obs_count * 0.5) and obs_count >= 4:
            warnings.append(f"{zero_count} of {obs_count} periods have zero activity (intermittent demand).")

        # 5. Constant series check (zero variance)
        val_std = float(np.std(values)) if obs_count > 1 else 0.0
        if obs_count >= min_observations and val_std < 1e-6:
            blocking.append("Time series exhibits zero variance (constant series) across all observed periods.")

        # 6. Outlier detection using IQR
        outliers_count = 0
        if obs_count >= 6:
            q25, q75 = np.percentile(values, [25, 75])
            iqr = q75 - q25
            if iqr > 1e-4:
                lower_bound = q25 - 1.5 * iqr
                upper_bound = q75 + 1.5 * iqr
                outliers_count = int(np.sum((values < lower_bound) | (values > upper_bound)))
                if outliers_count > 0:
                    warnings.append(f"Identified {outliers_count} statistical outlier periods outside 1.5x IQR.")

        # Determine status
        if blocking:
            status = DataQualityStatus.INSUFFICIENT_DATA if obs_count < min_observations else DataQualityStatus.INVALID
            is_ready = False
        elif warnings:
            status = DataQualityStatus.READY_WITH_WARNINGS
            is_ready = True
        else:
            status = DataQualityStatus.READY
            is_ready = True

        quality = ForecastDataQuality(
            status=status,
            observation_count=obs_count,
            frequency=frequency,
            date_from=first_date,
            date_to=last_date,
            missing_values=missing_vals,
            zero_periods_count=zero_count,
            outliers_detected=outliers_count,
            warnings=warnings,
            blocking_reasons=blocking,
        )

        return QualityGateResult(quality, is_ready)
