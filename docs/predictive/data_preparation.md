# Time-Series Data Preparation & Quality Gate

## Overview
Forecasting reliability is fundamentally bounded by the quality and temporal integrity of the underlying historical data. NEXUS implements a deterministic data preparation and validation layer before model fitting.

---

## 1. Frequency Normalization & Calendar Alignment
The `TimeSeriesPreparer` converts discrete transactional event records into continuous time series:
- **Daily (`daily`)**: Aggregates calendar days (`D`).
- **Weekly (`weekly`)**: Aggregates Monday-anchored weeks (`W-MON`).
- **Monthly (`monthly`)**: Aggregates month-start calendar intervals (`MS`).

### Gap Handling
- Active business transaction dates are aggregated directly.
- Missing intermediate dates within the observation span are aligned to zero with explicit tracking (`is_zero=True`).
- True zero activity is logged explicitly and differentiated from missing telemetry.

---

## 2. Quality Gate (`TimeSeriesQualityGate`)
The quality gate evaluates 6 core dimensions:
1. **Observation Count**:
   - Monthly: Configurable minimum (default: 4 observations for demo/test, recommended 18–24 for production seasonality).
   - Weekly: Configurable minimum (default: 8 observations).
   - Daily: Configurable minimum (default: 14 observations).
2. **Missing Values**:
   - Detection of NaN or null targets in the series.
3. **Zero Activity Proportion**:
   - Warns if > 40% of observations are zero; blocks if > 80% are zero.
4. **Variance & Constant Series**:
   - Detects zero or near-zero variance where models cannot fit.
5. **Outlier Auditing**:
   - Audits extreme values using standard Interquartile Range ($Q1 - 1.5 \cdot IQR$, $Q3 + 1.5 \cdot IQR$). Outliers are audited and documented in the quality warnings, but never deleted or modified in historical records.
6. **Recency**:
   - Audits whether the series terminates within a reasonable horizon of the evaluation date.

### Quality Status Outcomes
- `READY`: All validation checks pass without warnings.
- `READY_WITH_WARNINGS`: Sufficient observations exist, but potential anomalies, high zero ratios, or moderate gaps were audited.
- `INSUFFICIENT_DATA`: Observation count falls below strict threshold.
- `INVALID`: Constant series, all zeros, or corrupt values.
