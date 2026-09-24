# NEXUS Data Profiling Design

## 1. Objective
Data Profiling in NEXUS provides instantaneous, deterministic structural telemetry on any table or tabular stream. It eliminates guesswork about data shapes, null volumes, categorical skew, and numeric ranges.

---

## 2. Profiling Metrics Catalog

### 2.1 Dimensional Metrics
- **Total Row Count ($N$)**: The complete volume of rows scanned.
- **Total Column Count ($M$)**: The width of the relation.
- **Duplicate Row Count**: Count of records where all column values are identical to an earlier row.

### 2.2 Column-Level Metrics
- **Logical Type Inference**:
  - `integer`: Whole numbers ($1, 2, 100$).
  - `decimal`: Fixed-point currency or fractional numbers ($19.99$).
  - `boolean`: Logical true/false flags.
  - `datetime` / `date`: ISO-8601 timestamps and calendar dates.
  - `string`: Free text or categorical labels.
- **Null Frequency**:
  $$\text{Null \%} = \left(\frac{\text{Null Count}}{N}\right) \times 100$$
- **Cardinality & Uniqueness**:
  - `unique_count`: Distinct non-null values.
  - `is_unique`: True if $unique\_count = N$, identifying candidate primary or alternate keys.

### 2.3 Numeric Descriptive Statistics
For all numeric and decimal columns, the profiler computes:
- **Minimum & Maximum**: Lowest and highest recorded bounds.
- **Arithmetic Mean**:
  $$\bar{x} = \frac{1}{n} \sum_{i=1}^n x_i$$
- **Median**: 50th percentile rank value, resilient to outlier distortion.
- **Sample Standard Deviation**:
  $$s = \sqrt{\frac{1}{n - 1} \sum_{i=1}^n (x_i - \bar{x})^2}$$
- **Sum**: Total accumulated volume (e.g. cumulative sales, inventory units).

### 2.4 Temporal & Categorical Metrics
- **Date Range**: Earliest recorded date, latest recorded date, and total active calendar span in days.
- **Categorical Frequency**: Top $N$ distinct values with occurrence counts and percentage shares.
