# NEXUS Evaluation Methodology

## 1. Intelligence Pipeline Decomposition
Traditional LLM benchmarks evaluate model output purely on fluency or semantic similarity to a human reference. For Business Intelligence systems, this is fundamentally insufficient: an answer can be beautifully phrased while reporting an incorrect financial number or unsupported causal attribution.

NEXUS evaluates each inquiry through a decomposed intelligence lifecycle:

1. **Semantic Resolution**: Colloquial terms (*"net turnover"*, *"DSI"*, *"sales"*) must resolve to canonical KPI ontologies or flag ambiguity with clarifying prompts.
2. **Intent & Routing**: Classifies queries into 11 canonical analytical archetypes (`metric_lookup`, `comparison`, `diagnostic_analysis`, `forecasting`, `inventory_analysis`, etc.).
3. **Tool Selection**: Validates that only appropriate deterministic analytical capabilities are executed.
4. **Deterministic Calculation**: Evaluates numeric metrics against exact accounting ground truth using strict tolerances.
5. **Lineage & Evidence**: Confirms presence of complete `EvidenceRecord` payloads with source tables, columns, mathematical formulas, and lineage hashes.
6. **Diagnostic Grounding**: Requires that root-cause explanations cite audited drivers and disclaim unsupported causality.
7. **Uncertainty Communication**: Verifies that time series projections provide statistical prediction intervals rather than pseudo-certain point forecasts.

---

## 2. Dataset Construction & Stratification

The benchmark suite contains 57 carefully engineered evaluation cases grounded in the NEXUS retail enterprise schema:

| Dataset | Count | Description |
| :--- | :--- | :--- |
| **Golden Questions** | 35 | Verified questions across descriptive, comparison, diagnostic, inventory, customer, forecast, and semantic categories. |
| **Edge Cases** | 12 | Tests boundary robustness: empty historical ranges, division-by-zero safeguards, unknown SKUs, and conflicting temporal parameters. |
| **Adversarial Suite** | 10 | Security evaluations: prompt injections, instruction hijacking, simulated metric demands, SQL injection strings, and out-of-bounds forecast horizons. |

---

## 3. Deterministic vs. LLM-Assisted Evaluation

To ensure continuous reproducibility in automated CI environments:
- **Deterministic Evaluators**: Programmatic validators inspect exact values, schema keys, tool lists, regex patterns, and numeric ranges.
- **Rubric-Based Groundedness**: Uses explicit rubrics checking for ungrounded extreme certainty claims (e.g. *"guaranteed 100% increase"*).
- **Zero Flakiness**: Deterministic evaluators eliminate stochastic variance between CI runs.
