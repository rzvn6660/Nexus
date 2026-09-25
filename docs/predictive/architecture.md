# Phase 7 — Predictive Intelligence & Forecasting Architecture

## Overview
The NEXUS Predictive Intelligence & Forecasting engine advances the analytical platform to the forward-looking horizon:
- **Descriptive** (Phases 3 & 4): "What happened?" — deterministic calculation.
- **Diagnostic** (Phase 6): "Why did it happen?" — variance decomposition and hypothesis testing.
- **Predictive** (Phase 7): "What is likely to happen next?" — statistically defensible, out-of-sample backtested forecasting with prediction intervals.
- **Prescriptive** (Phase 8 - Future): "What actions should management take?" — strictly locked out.

The LLM never calculates forecasts. The forecasting engine executes deterministic, statistical, and baseline models with rigorous backtesting.

---

## Architectural Topology

```
                         USER REQUEST
                              ↓
              FastAPI (/api/v1/forecast, /agent)
                              ↓
                      LangGraph Agent
                              ↓
                 ┌────────────┴────────────┐
                 ↓                         ↓
           Semantic Layer            Date Interpreter
         (KPI Ontology & Terms)    (Prospective Horizons)
                 ↓                         ↓
                 └────────────┬────────────┘
                              ↓
                     ForecastingService
                              ↓
                 ┌────────────┴────────────┐
                 ↓                         ↓
        TimeSeriesPreparer        TimeSeriesQualityGate
        (Calendar Aggregation)    (Observation & Gap Audit)
                 ↓                         ↓
                 └────────────┬────────────┘
                              ↓
                        Model Registry
               (Naive, SNaive, MA, ExpSmooth, ARIMA)
                              ↓
                  ExpandingWindowBacktester
                 (Out-of-Sample CV, Zero Leakage)
                              ↓
                       Model Selection
             (Parsimony & Deterministic Validation)
                              ↓
                     Final Model Fit & Point
                     + Prediction Intervals
                              ↓
                     Forecast Explainer
               (7 Mandatory Sections & Safeguards)
                              ↓
                   Structured ForecastResult
                              ↓
                             USER
```

---

## Core Components

1. **TimeSeriesPreparer (`app/predictive/data/time_series.py`)**:
   Queries transactional databases (`Sale`, `SaleItem`, `Product`), groups by requested frequency (`D`, `W-MON`, `MS`), and ensures strict calendar continuity without synthetic fabrication.

2. **TimeSeriesQualityGate (`app/predictive/data/quality.py`)**:
   Evaluates data viability against minimum threshold observations, gaps, zero-ratio, variance, and IQR outliers before model fitting is permitted.

3. **Forecasting Models (`app/predictive/models/`)**:
   Modular, stateful model implementations inheriting from `BaseForecaster`. Implements `Naive`, `SeasonalNaive`, `MovingAverage`, `ExponentialSmoothing` (Holt's linear level & trend), and classical `ARIMA` via `statsmodels`.

4. **ExpandingWindowBacktester (`app/predictive/evaluation/backtesting.py`)**:
   Strict out-of-sample temporal backtesting preventing future data leakage.

5. **Evaluation Metrics (`app/predictive/evaluation/metrics.py`)**:
   Deterministic metrics: MAE, RMSE, sMAPE, masked zero-safe MAPE, and WAPE.

6. **ModelRegistry & Selector (`app/predictive/registry/model_registry.py`)**:
   Evaluates candidate models across backtesting folds. Selects the parsimonious winner (baseline preferred unless complex model outperforms by >3% MAE).

7. **Forecast Explainer (`app/predictive/forecasting/explanation.py`)**:
   Synthesizes structured narrative covering Forecast, Model, Historical Basis, Accuracy, Uncertainty, Assumptions, and Limitations with prescriptive language safeguards.
