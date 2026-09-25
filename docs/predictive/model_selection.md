# Deterministic Model Selection

## Overview
Model selection in NEXUS is entirely deterministic and evidence-driven. LLMs are never permitted to declare a "winning" forecasting model based on text descriptions or intuition.

---

## 1. Candidate Pool
For any series passing the `TimeSeriesQualityGate`, the candidate pool includes:
1. `naive` (Last observed value baseline)
2. `seasonal_naive` (Cycle lagged baseline)
3. `moving_average` (Rolling window baseline)
4. `exponential_smoothing` (Holt's linear level & trend)
5. `arima` (Autoregressive Integrated Moving Average)

---

## 2. Selection Policies
- **`validated_best` (Default)**:
  Runs out-of-sample expanding window backtesting across all candidates. Evaluates Mean Absolute Error (MAE) and Root Mean Squared Error (RMSE).
- **`baseline_only`**:
  Restricts candidates to `naive`, `seasonal_naive`, and `moving_average`.
- **`specific_model`**:
  Uses the model explicitly designated by the user, provided it successfully validates against the quality gate.

---

## 3. Parsimony Rule
To prevent overfitting on limited historical windows:
- If a complex statistical model (such as ARIMA) achieves lower MAE than Exponential Smoothing, but the relative improvement is less than **3%**, NEXUS selects the simpler, more stable model.
- If backtesting fails or is degenerate for all models, the system flags the forecast as unavailable rather than fabricating predictions.
