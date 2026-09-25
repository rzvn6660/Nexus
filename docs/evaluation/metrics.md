# NEXUS Evaluation Metrics Specification

## 1. Metric Catalog

NEXUS computes granular, multi-dimensional metrics rather than a single aggregated heuristic score:

### A. Intent Classification Accuracy
$$\text{Accuracy}_{\text{intent}} = \frac{\text{Correct Intent Classifications}}{\text{Total Intent-Evaluated Queries}} \times 100$$
- Evaluates mapping of user queries into canonical analytical archetypes (`metric_lookup`, `comparison`, `diagnostic_analysis`, `forecasting`, etc.).

### B. Semantic Resolution Accuracy
$$\text{Accuracy}_{\text{semantic}} = \frac{\text{Correct Canonical Mappings} + \text{Correct Ambiguity Flags}}{\text{Total Semantic Inquiries}} \times 100$$
- Measures canonical KPI resolution, synonym matching (*"turnover"* vs *"inventory turnover"*), and disambiguation triggers.

### C. Tool Selection Accuracy
$$\text{Accuracy}_{\text{tools}} = \frac{\text{Correct Tool Invocations}}{\text{Total Tool-Evaluated Queries}} \times 100$$
- Verifies that only appropriate deterministic tools are executed and that unsupported queries invoke zero tools.

### D. Numerical Accuracy
Exact tolerance match:
$$\text{Match} = (|y_{\text{act}} - y_{\text{exp}}| \le \epsilon_{\text{abs}}) \lor \left(\frac{|y_{\text{act}} - y_{\text{exp}}|}{|y_{\text{exp}}|} \le \epsilon_{\text{rel}}\right)$$
- Default parameters: $\epsilon_{\text{abs}} = 0.01$, $\epsilon_{\text{rel}} = 0.001$. Never uses vague LLM grading for deterministic numerical outputs.

### E. Evidence Completeness Score
- Ratio of completed required evidence attributes:
  - Source database tables
  - Source columns and filter predicates
  - Calculation formula and method descriptor
  - Cryptographic / lineage analysis identifier

### F. Groundedness Score
- Evaluates whether factual statements in the generated response are grounded in the backing `EvidenceRecord`. Penalizes ungrounded extreme certainty claims.

### G. Hallucination Rate
$$\text{Rate}_{\text{hallucination}} = \frac{\text{Cases with Fabricated Metrics or Ungrounded Claims}}{\text{Total Queries}} \times 100$$
- Target: $0.0\%$.

### H. Adversarial Defense Rate
$$\text{Rate}_{\text{defense}} = \frac{\text{Neutralized Injection & Security Attempts}}{\text{Total Adversarial Cases}} \times 100$$
- Target: $100.0\%$.

### I. Predictive Forecast Quality
Computed out-of-sample backtesting accuracy:
- **MAE** (Mean Absolute Error): $\frac{1}{n}\sum |y_t - \hat{y}_t|$
- **RMSE** (Root Mean Squared Error): $\sqrt{\frac{1}{n}\sum (y_t - \hat{y}_t)^2}$
- **sMAPE** (Symmetric Mean Absolute Percentage Error): $\frac{100\%}{n}\sum \frac{|\hat{y}_t - y_t|}{(|y_t| + |\hat{y}_t|)/2}$
- **Prediction Interval Verification**: Upper and lower uncertainty bounds present and non-negative.

### J. Latency Telemetry
- Total wall-clock duration from query receipt to structured response emission: Mean, Median, and 95th Percentile (P95) in milliseconds.
