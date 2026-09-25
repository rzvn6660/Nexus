# Uncertainty & Prediction Intervals

## Overview
A forecast without uncertainty is misleading. NEXUS enforces the principle:
> **"The system must NEVER present a forecast as certainty."**

---

## 1. Prediction Intervals vs. Confidence Intervals
- **Confidence Interval**: Quantifies uncertainty in the estimation of a population parameter (e.g. the true mean).
- **Prediction Interval**: Quantifies uncertainty in an individual future observation, incorporating both parameter estimation variance and irreducible disturbance (error variance):
  $$\hat{y}_{T+h} \pm t_{1 - \alpha/2, \nu} \cdot \hat{\sigma}_h$$

---

## 2. Invariance & Boundary Integrity
NEXUS mathematically validates that every point forecast satisfies:
$$\text{lower\_bound} \le \text{point\_forecast} \le \text{upper\_bound}$$

### Non-Negativity
For metrics with non-negative physical bounds (revenue, sales currency, physical unit counts, order volumes), the lower bound is constrained to $\max(0.0, \text{lower})$.

### Horizon Variance Expansion
As the forecast horizon $h$ extends further into the future, the prediction interval widens proportionally to $\sqrt{h}$ to reflect compounding epistemic uncertainty.

---

## 3. Communication Standards
The system explicitly forbids statements of certainty:
- **Forbidden**: "Revenue next month will be $130,000."
- **Mandated**: "Forecast revenue is $130,000 with an estimated 95% prediction interval of $115,000–$145,000."
