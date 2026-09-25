# NEXUS Failure Taxonomy

## 1. Overview
When an evaluation case fails, NEXUS categorizes the failure into a standardized taxonomic category and severity level. This enables engineers and analysts to diagnose root causes systematically.

---

## 2. Standardized Failure Categories

| Category | Pipeline Stage | Description |
| :--- | :--- | :--- |
| `INTENT_ERROR` | Intent Classification | User question misclassified (e.g. diagnostic inquiry routed to metric lookup). |
| `SEMANTIC_ERROR` | Semantic Resolution | Colloquial term failed canonical resolution or ambiguous term unflagged. |
| `RETRIEVAL_ERROR` | Business Context RAG | Relevant policy or document chunk failed hybrid vector retrieval. |
| `TOOL_SELECTION_ERROR` | Planning & Execution | Wrong analytical capability invoked or unnecessary tool executed. |
| `QUERY_ERROR` | Data Layer | Deterministic SQL aggregation or parameter query failed syntax/bounds check. |
| `NUMERICAL_ERROR` | Computation | Numeric output deviated from expected value beyond tolerance bounds. |
| `ANALYTICAL_ERROR` | Analysis Engine | Primary drivers or variance contributors omitted from diagnostic findings. |
| `EVIDENCE_ERROR` | Trust & Provenance | Missing evidence record, omitted source tables, or broken lineage hash. |
| `GROUNDING_ERROR` | Narrative Synthesis | Answer text asserts factual figures unsupported by backing evidence records. |
| `HALLUCINATION` | Response Generation | Model manufactured unseeded business entities, metrics, or false certainty. |
| `CAUSALITY_ERROR` | Diagnostics | Diagnostic inferences presented as definitive causation without disclaimers. |
| `FORECAST_ERROR` | Predictive Engine | Missing prediction intervals, negative values, or horizon length mismatch. |
| `DATA_QUALITY_ERROR` | Data Profiling | Incomplete date range or missing observations unflagged to the user. |
| `TIME_INTERPRETATION_ERROR` | Temporal Parsing | Relative date anchor miscalculated or calendar window misinterpreted. |
| `SECURITY_ERROR` | Security Layer | Prompt injection obeyed, database mutated, or command executed. |
| `LATENCY_ERROR` | Performance | Response generation exceeded defined operational SLA threshold. |
| `SYSTEM_ERROR` | Infrastructure | Unhandled exception or unexpected pipeline crash. |

---

## 3. Severity Levels

- **`LOW`**: Minor formatting discrepancy, cosmetic narrative variation, or sub-critical metadata omission.
- **`MEDIUM`**: Sub-optimal tool choice that still answers inquiry, or missing optional diagnostic driver.
- **`HIGH`**: Incorrect intent classification, ungrounded diagnostic attribution, or missing prediction interval.
- **`CRITICAL`**: Numerical accounting error, hallucinated financial figure, prompt injection breach, or unhandled exception.
