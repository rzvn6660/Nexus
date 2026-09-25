# Forecast Evaluation Metrics

## Overview
Forecasting metrics in NEXUS are strictly deterministic. Zero denominators are safely handled to guarantee no NaN or infinite values propagate to users or APIs.

---

## Supported Metrics

### 1. Mean Absolute Error (MAE)
$$\text{MAE} = \frac{1}{n} \sum_{t=1}^n |y_t - \hat{y}_t|$$
- **Usage**: Primary ranking metric for model selection. Scale-dependent, robust to isolated outliers.

### 2. Root Mean Squared Error (RMSE)
$$\text{RMSE} = \sqrt{\frac{1}{n} \sum_{t=1}^n (y_t - \hat{y}_t)^2}$$
- **Usage**: Penalizes large deviations heavily. Useful when extreme errors carry outsized business consequences.

### 3. Symmetric Mean Absolute Percentage Error (sMAPE)
$$\text{sMAPE} = \frac{100\%}{n} \sum_{t=1}^n \frac{2 |y_t - \hat{y}_t|}{|y_t| + |\hat{y}_t|}$$
- **Bound**: Constrained between $0\%$ and $200\%$.
- **Zero Handling**: When both $y_t = 0$ and $\hat{y}_t = 0$, error component is assigned $0.0$.

### 4. Mean Absolute Percentage Error (MAPE)
$$\text{MAPE} = \frac{100\%}{n} \sum_{t=1}^n \left|\frac{y_t - \hat{y}_t}{y_t}\right|$$
- **Safety Rule**: When $y_t = 0$, standard MAPE is mathematically undefined. NEXUS calculates MAPE over non-zero elements only; if all actuals are zero, returns `None` and documents the condition.

### 5. Weighted Absolute Percentage Error (WAPE)
$$\text{WAPE} = \frac{\sum_{t=1}^n |y_t - \hat{y}_t|}{\sum_{t=1}^n |y_t|}$$
- **Usage**: Aggregates total error over total volume. Avoids disproportionate inflation from low-volume periods.
