# Forecasting Models

## Overview
NEXUS adheres to an evidence-based baseline philosophy:
> **"A complex model should NOT automatically be considered better than a baseline. Model selection must be evidence-based."**

---

## Supported Model Families

### 1. Naive Model (`naive`)
- **Philosophy**: Simplest deterministic baseline. Assumes future value equals the last observed value:
  $$\hat{y}_{t+h} = y_t$$
- **Uncertainty**: Modeled as a discrete random walk with variance expanding proportionally to forecast horizon:
  $$\sigma_h = \hat{\sigma}_{\text{res}} \sqrt{h}$$

### 2. Seasonal Naive Model (`seasonal_naive`)
- **Philosophy**: Assumes future value equals the value observed in the identical period of the previous cycle:
  $$\hat{y}_{t+h} = y_{t+h-m(k+1)}$$
  where $m$ is the seasonal period (12 for monthly, 52 for weekly, 7 for daily).
- **Graceful Fallback**: If observation count is less than $m$, falls back gracefully to standard naive.

### 3. Moving Average Model (`moving_average`)
- **Philosophy**: Smooths high-frequency noise by projecting the rolling arithmetic mean of the most recent $k$ periods (default $k=3$):
  $$\hat{y}_{t+h} = \frac{1}{k} \sum_{i=0}^{k-1} y_{t-i}$$
- **Uncertainty**: Uses sample standard deviation of residuals scaled across prospective steps.

### 4. Exponential Smoothing Model (`exponential_smoothing`)
- **Philosophy**: Holt's linear trend model capturing both baseline level and linear trajectory:
  $$\ell_t = \alpha y_t + (1 - \alpha)(\ell_{t-1} + b_{t-1})$$
  $$b_t = \beta (\ell_t - \ell_{t-1}) + (1 - \beta) b_{t-1}$$
  $$\hat{y}_{t+h} = \ell_t + h b_t$$
- **Parameter Estimation**: Grid search / L-BFGS-B optimization minimizing sum of squared errors over $\alpha \in [0.05, 0.95]$ and $\beta \in [0.01, 0.50]$.

### 5. Classical ARIMA (`arima`)
- **Philosophy**: Autoregressive Integrated Moving Average using `statsmodels.tsa.arima.model.ARIMA`.
- **Candidate Configurations**: Evaluates $(1,0,0)$, $(0,1,1)$, $(1,1,0)$, $(1,1,1)$, $(0,1,0)$.
- **Selection**: Lowest Akaike Information Criterion (AIC) during in-sample estimation.
- **Fail-Safe**: If convergence fails or stationarity conditions are violated, falls back to Holt's exponential smoothing.
