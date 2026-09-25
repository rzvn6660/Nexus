# Lightweight Model Registry

## Overview
The NEXUS model registry records metadata, evaluation benchmarks, and parameters for candidate and selected forecasting models.

---

## 1. Registry Record Schema
Each registered model entry encapsulates:
```json
{
  "name": "exponential_smoothing",
  "version": "1.0",
  "model_type": "holt_linear",
  "parameters": {
    "alpha": 0.35,
    "beta": 0.08
  },
  "training_period": {
    "from": "2024-01-01",
    "to": "2024-09-01"
  },
  "frequency": "monthly",
  "evaluation_metrics": {
    "mae": 1250.45,
    "rmse": 1620.10,
    "smape": 5.4,
    "mape": 5.2,
    "wape": 4.9
  },
  "selected": true,
  "selection_reason": "Outperformed moving_average and naive with lowest expanding-window MAE (1250.45)."
}
```

---

## 2. Model Versioning & Provenance
- Models are assigned semantic versions (e.g. `1.0`).
- Model parameters are deterministically serializable to allow full post-hoc reproducibility.
- Backtest logs retain the historical cross-validation score for each candidate evaluated during the request.
