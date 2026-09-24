# NEXUS Deterministic Analytics Engine Architecture

## 1. Overview & Core Philosophy

The NEXUS Analytics Engine (Phase 3) provides a mathematically rigorous, fully deterministic layer that computes business metrics, aggregates temporal trends, evaluates diagnostic variances, and performs parametric/non-parametric statistical analyses without relying on large language models or stochastic processes.

```
RAW BUSINESS DATA (PostgreSQL)
             ↓
TRUSTED DATA LAYER (Phase 2 Models & Ingestion)
             ↓
ANALYTICS SERVICE LAYER (Phase 3 Deterministic Engine)
             ↓
TYPED ANALYTICAL RESULTS + EVIDENCE RECORDS
             ↓
FUTURE LANGGRAPH AGENTS (Phase 4 Natural Language Augmentation)
```

### Key Architectural Tenets
1. **Zero LLM Calculations**: Every quantitative calculation (revenue, margins, variance decomposition, RFM quantile binning, p-values) is computed exclusively using SQL, Python, Pandas, NumPy, or SciPy.
2. **Fixed Financial Precision**: All financial amounts utilize fixed-point `Decimal` (`NUMERIC(12, 2)`) to eliminate floating-point rounding hazards.
3. **Audit Evidence Attached**: Every response includes an `EvidenceRecord` declaring exact mathematical formulas, source tables/columns, applied filters, and analytical assumptions.
4. **Direct Service Interface**: The `AnalyticsService` facade is callable directly by FastAPI endpoints AND will be imported by future LangGraph tools without making HTTP hops.

---

## 2. Directory Structure

```
backend/app/analytics/
├── __init__.py
├── core/
│   ├── types.py            # Enums: PeriodGranularity, MetricUnit, TrendDirection, etc.
│   ├── context.py          # Strongly-typed AnalysisContext with date intervals & filters
│   ├── exceptions.py       # Domain exceptions: InsufficientDataError, InvalidContextError
│   └── models.py           # Typed results: MetricValue, ComparisonResult, BreakdownResult, etc.
│
├── evidence/
│   ├── models.py           # EvidenceRecord schema for complete auditability
│   └── builder.py          # Fluent EvidenceBuilder utility
│
├── metrics/
│   ├── definitions.py      # MetricRegistry with business definitions, source tables, and limitations
│   ├── financial.py        # 12 Core financial metrics & period-over-period comparisons
│   └── expenses.py         # Operating expenses and recurring overhead allocations
│
├── descriptive/
│   ├── time_series.py      # Chronological rollups (Daily, Weekly, Monthly, Quarterly) & growth
│   └── segmentation.py     # Breakdown by customer segment, geographic city, warehouse
│
├── diagnostic/
│   ├── variance.py         # Multi-entity revenue variance dissection (top positive/negative drivers)
│   └── decomposition.py    # Price / Volume / Mix mathematical decomposition
│
├── customer/
│   ├── rfm.py              # Recency, Frequency, Monetary quantile scoring (1-5)
│   ├── cohorts.py          # Acquisition-month retention and spend progression (M0, M1, ...)
│   └── repeat_purchase.py  # One-time vs repeat customers and order frequency distribution
│
├── product/
│   ├── performance.py      # Transparent rankings by revenue, profit, units, margin
│   └── velocity.py         # Daily units velocity (units / days in interval)
│
├── inventory/
│   ├── stock.py            # Current inventory valuation, out-of-stock, and reorder alerts
│   └── turnover.py         # Inventory turnover ratio and Days Sales of Inventory (DSI)
│
├── statistics/
│   ├── descriptive.py      # Parametric & non-parametric stats (mean, median, IQR, percentiles)
│   ├── correlation.py      # Pearson & Spearman correlation with causation warning
│   └── hypothesis.py       # Two-sample Welch's t-test with p-values and interpretation
│
└── service.py              # Master AnalyticsService facade coordinating all engines
```
