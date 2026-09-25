# NEXUS Phase 9 — Evaluation & Benchmarking Report

**Generated:** 2026-09-25 19:47:24 UTC  
**System:** NEXUS Agentic Business Intelligence Platform  
**Evaluation Harness:** Pipeline-Wide Multi-Dimensional Correctness

---

## 1. Executive Summary

- **Total Benchmark Cases:** 57
- **Passed Cases:** 38
- **Failed Cases:** 36
- **Pass Rate:** **66.7%**

| Evaluation Dimension | Accuracy / Score | Benchmark Target | Status |
| :--- | :--- | :--- | :--- |
| **Intent Classification** | 79.2% | ≥ 95.0% | ⚠️ REVIEW |
| **Semantic Resolution** | 100.0% | ≥ 90.0% | ✅ PASS |
| **Tool Selection** | 77.1% | ≥ 95.0% | ⚠️ REVIEW |
| **Numerical Accuracy (Exact Tolerance)** | 85.7% | 100.0% | ⚠️ REVIEW |
| **Analytical Driver Coverage** | 92.5% | ≥ 85.0% | ✅ PASS |
| **Evidence Completeness** | 94.7% | ≥ 90.0% | ✅ PASS |
| **Groundedness Score** | 89.8% | ≥ 90.0% | ⚠️ REVIEW |
| **Hallucination Rate** | 0.0% | ≤ 1.0% | ✅ PASS |
| **Adversarial / Injection Defense** | 100.0% | 100.0% | ✅ PASS |

---

## 2. Latency Telemetry

- **Mean Latency:** 30.2 ms
- **Median Latency:** 15.1 ms
- **P95 Latency:** 236.8 ms

---

## 3. Forecast Quality (Backtesting)

- **MAE (Mean Absolute Error):** 12.4
- **RMSE (Root Mean Squared Error):** 15.8
- **sMAPE (Symmetric MAPE):** 5.20%

---

## 4. Failure Taxonomy & Root Causes

| Case ID | Category | Severity | Stage | Details |
| :--- | :--- | :--- | :--- | :--- |
| `GOLD-COMP-001` | `NUMERICAL_ERROR` | `CRITICAL` | `numeric_verification` | Expected numeric field 'growth_rate' with value 119.35 was not found in response |
| `GOLD-COMP-001` | `ANALYTICAL_ERROR` | `HIGH` | `diagnostic_analysis` | Diagnostic result failed to identify critical business drivers: ['June', 'May'] |
| `GOLD-COMP-002` | `INTENT_ERROR` | `HIGH` | `intent_classification` | Expected intent 'period_comparison' but got 'product_analysis' |
| `GOLD-COMP-003` | `INTENT_ERROR` | `HIGH` | `intent_classification` | Expected intent 'period_comparison' but got 'metric_lookup' |
| `GOLD-COMP-003` | `ANALYTICAL_ERROR` | `HIGH` | `diagnostic_analysis` | Diagnostic result failed to identify critical business drivers: ['Gross profit increased'] |
| `GOLD-COMP-004` | `INTENT_ERROR` | `HIGH` | `intent_classification` | Expected intent 'product_comparison' but got 'diagnostic_analysis' |
| `GOLD-COMP-004` | `TOOL_SELECTION_ERROR` | `HIGH` | `tool_selection` | Missing expected analytical tools. Expected one of ['get_product_rankings'], but got ['run_variance_analysis', 'get_financial_summary'] |
| `GOLD-DIAG-001` | `ANALYTICAL_ERROR` | `HIGH` | `diagnostic_analysis` | Diagnostic result failed to identify critical business drivers: ['category_variance', 'product_contribution'] |
| `GOLD-DIAG-002` | `INTENT_ERROR` | `HIGH` | `intent_classification` | Expected intent 'diagnostic_analysis' but got 'metric_lookup' |
| `GOLD-DIAG-002` | `ANALYTICAL_ERROR` | `HIGH` | `diagnostic_analysis` | Diagnostic result failed to identify critical business drivers: ['cost of goods sold', 'selling price'] |
| `GOLD-DIAG-003` | `ANALYTICAL_ERROR` | `HIGH` | `diagnostic_analysis` | Diagnostic result failed to identify critical business drivers: ['SKU-A', 'SKU-B'] |
| `GOLD-DIAG-003` | `CAUSALITY_ERROR` | `MEDIUM` | `causality_safeguards` | Analysis presents diagnostic inferences without required causality or limitation safeguards |
| `GOLD-DIAG-004` | `INTENT_ERROR` | `HIGH` | `intent_classification` | Expected intent 'diagnostic_analysis' but got 'metric_lookup' |
| `GOLD-DIAG-005` | `SYSTEM_ERROR` | `CRITICAL` | `execution` | Pipeline exception during evaluation: 'NoneType' object has no attribute 'lower' |
| `GOLD-DIAG-005` | `TOOL_SELECTION_ERROR` | `HIGH` | `tool_selection` | Missing expected analytical tools. Expected one of ['get_repeat_purchase_rate', 'get_customer_segments'], but got [] |
| `GOLD-DIAG-005` | `EVIDENCE_ERROR` | `CRITICAL` | `evidence_validation` | NEXUS failed trust contract: Answer presented without backing deterministic evidence |
| `GOLD-DIAG-005` | `ANALYTICAL_ERROR` | `HIGH` | `diagnostic_analysis` | Diagnostic result failed to identify critical business drivers: ['repeat purchase', 'order frequency'] |
| `GOLD-DIAG-005` | `CAUSALITY_ERROR` | `MEDIUM` | `causality_safeguards` | Analysis presents diagnostic inferences without required causality or limitation safeguards |
| `GOLD-INVT-001` | `ANALYTICAL_ERROR` | `HIGH` | `diagnostic_analysis` | Diagnostic result failed to identify critical business drivers: ['Desk Organizer Box #2', 'Gadget B'] |
| `GOLD-INVT-002` | `EVIDENCE_ERROR` | `HIGH` | `evidence_validation` | Missing expected source tables in evidence lineage: ['sales'] |
| `GOLD-INVT-003` | `TOOL_SELECTION_ERROR` | `HIGH` | `tool_selection` | Missing expected analytical tools. Expected one of ['get_product_velocity'], but got [] |
| `GOLD-INVT-003` | `EVIDENCE_ERROR` | `CRITICAL` | `evidence_validation` | NEXUS failed trust contract: Answer presented without backing deterministic evidence |
| `GOLD-INVT-003` | `ANALYTICAL_ERROR` | `HIGH` | `diagnostic_analysis` | Diagnostic result failed to identify critical business drivers: ['units_per_day'] |
| `GOLD-CUST-001` | `TOOL_SELECTION_ERROR` | `HIGH` | `tool_selection` | Missing expected analytical tools. Expected one of ['get_repeat_purchase_rate'], but got ['get_repeat_purchase'] |
| `GOLD-CUST-001` | `EVIDENCE_ERROR` | `HIGH` | `evidence_validation` | Missing expected source tables in evidence lineage: ['customers'] |
| `GOLD-CUST-003` | `INTENT_ERROR` | `HIGH` | `intent_classification` | Expected intent 'customer_lookup' but got 'unsupported' |
| `GOLD-CUST-003` | `TOOL_SELECTION_ERROR` | `HIGH` | `tool_selection` | Missing expected analytical tools. Expected one of ['get_repeat_purchase_rate'], but got [] |
| `GOLD-CUST-003` | `EVIDENCE_ERROR` | `CRITICAL` | `evidence_validation` | NEXUS failed trust contract: Answer presented without backing deterministic evidence |
| `GOLD-UNSUP-001` | `INTENT_ERROR` | `HIGH` | `intent_classification` | Expected intent 'unsupported' but got 'customer_analysis' |
| `GOLD-UNSUP-001` | `TOOL_SELECTION_ERROR` | `MEDIUM` | `tool_selection` | Expected zero tools for unsupported query, but executed: ['get_customer_segments'] |
| `GOLD-UNSUP-002` | `INTENT_ERROR` | `HIGH` | `intent_classification` | Expected intent 'unsupported' but got 'inventory_analysis' |
| `GOLD-UNSUP-002` | `TOOL_SELECTION_ERROR` | `MEDIUM` | `tool_selection` | Expected zero tools for unsupported query, but executed: ['get_inventory_overview'] |
| `GOLD-UNSUP-003` | `INTENT_ERROR` | `HIGH` | `intent_classification` | Expected intent 'unsupported' but got 'comparison' |
| `GOLD-UNSUP-003` | `TOOL_SELECTION_ERROR` | `MEDIUM` | `tool_selection` | Expected zero tools for unsupported query, but executed: ['get_financial_summary'] |
| `EDGE-003` | `ANALYTICAL_ERROR` | `HIGH` | `diagnostic_analysis` | Diagnostic result failed to identify critical business drivers: ['product not found', 'SKU-UNKNOWN-9999'] |
| `EDGE-004` | `INTENT_ERROR` | `HIGH` | `intent_classification` | Expected intent 'unsupported' but got 'product_analysis' |

---

## 5. Regression Detection vs Baseline

**Regression Status:** ✅ STABLE / NO REGRESSIONS

- All metric dimensions meet or exceed baseline stability thresholds.

---

## 6. Known Weaknesses & Future Roadmap

1. **Cold Start Data Requirements**: Forecasting requires a minimum of 6 historical periods for seasonal models; shorter series fall back gracefully to linear/moving average.
2. **Ambiguous Terminology Without Domain**: Multi-domain terms (such as standalone 'turnover') require interactive clarification rather than aggressive assumption.
3. **External Benchmarks**: Operational metrics outside the transactional retail schema (e.g. employee productivity, market share) are rejected safely.

---
*Report generated autonomously by NEXUS Evaluation Harness.*