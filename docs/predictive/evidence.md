# Forecast Evidence & Provenance

## Overview
Phase 7 introduces `ForecastEvidence` to complement the existing multi-tier evidence architecture:
- **Phase 3**: `EvidenceRecord` (SQL queries, row counts, exact aggregated figures).
- **Phase 5**: `RAGEvidence` (Document chunks, cosine similarity, ontology references).
- **Phase 6**: `InvestigationEvidence` (Diagnostic hypotheses, contribution percentages, audit statuses).
- **Phase 7**: `ForecastEvidence` (Training range, model hyperparameters, backtest validation scores, data quality checks).

---

## 1. Structure of `ForecastEvidence`
```python
class ForecastEvidence(BaseModel):
    forecast_id: str
    source_tables: list[str]
    source_columns: list[str]
    target_metric: str
    filters: dict[str, Any]
    training_range: dict[str, Optional[str]]
    forecast_horizon: int
    frequency: str
    model: str
    model_parameters: dict[str, Any]
    validation_method: str
    validation_metrics: EvaluationMetrics
    selected_model_rationale: str
    assumptions: list[str]
    limitations: list[str]
    data_quality_status: str
    generated_at: str
```

---

## 2. Auditability
Every generated forecast exposes:
1. Exact source tables (`sales`, `sale_items`, `products`).
2. Earliest and latest historical timestamps used in training.
3. Number of backtesting folds and out-of-sample metrics.
4. Rationale for model selection.
5. Known epistemic assumptions and limitations.
