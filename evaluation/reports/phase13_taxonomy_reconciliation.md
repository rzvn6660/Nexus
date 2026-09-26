# NEXUS Phase 13: Taxonomy Reconciliation & Decision Architecture Cleanup Report

**Date:** 2026-09-26  
**Phase:** 13 (Architecture Cleanup & Evaluation Alignment)  
**Status:** Completed  
**Authoritative Module:** [`backend/app/decisions/taxonomy.py`](file:///c:/Users/rizvi/nexus/backend/app/decisions/taxonomy.py)  

---

## 1. Executive Summary & Core Principle

> **CORE PRINCIPLE**:  
> *"NEXUS needs one coherent semantic contract. The taxonomy must describe user intent independently of implementation details. Evaluation must test the same contract that production uses. Tools are implementation mechanisms. Analytics are computation mechanisms. Intent describes user goals. Fix the contract first."*

In Phase 12C, empirical benchmarking revealed that 54.17% (26/48) of evaluation intent questions and 66.67% (20/30) of tool selection questions referenced legacy labels that did not exist in runtime enums or registries. Because the Decision Gateway strictly enforces Candidate Boundaries (never fabricating out-of-bounds decisions), this created an artificial ceiling in benchmark accuracy.

Phase 13 establishes **one authoritative canonical taxonomy** of 12 analytical user intents, creates a centralized backward compatibility mapping layer, reconciles runtime tool names with evaluation datasets, and verifies candidate consistency across all decision providers without modifying question semantics or weakening tests.

---

## 2. Previous Taxonomy & Problems Discovered

### The Previous Runtime Taxonomy (`IntentCategory` Phase 4)
The runtime enum exposed 11 categories:
`metric_lookup`, `comparison`, `trend`, `product_analysis`, `customer_analysis`, `inventory_analysis`, `expense_analysis`, `diagnostic_analysis`, `statistical_analysis`, `forecasting`, `unsupported`.

### The Evaluation Dataset Labels (Legacy Benchmark)
The evaluation datasets contained 12 distinct labels:
`metric_lookup`, `ranking_lookup`, `category_breakdown`, `period_comparison`, `product_comparison`, `diagnostic_analysis`, `inventory_lookup`, `customer_lookup`, `forecast_lookup`, `semantic_resolution`, `unsupported`, `product_lookup`.

### Problems Identified:
1. **Taxonomy Mismatch**: Labels such as `category_breakdown`, `inventory_lookup`, and `forecast_lookup` were absent from `IntentCategory`. When the Decision Gateway supplied `supported_intents = [e.value for e in IntentCategory]`, bounded providers could never pick them.
2. **Conflating Intent with Subtype**: A user asking *"Which category contributed the most revenue?"* has a `product_analysis` intent with a `category_breakdown` subtype. Overloading the primary intent with dimensional details fractured top-level routing.
3. **Tool Name Drift**: 8 tools in the evaluation expectations (`get_top_products`, `get_category_performance`, `get_inventory_status`, etc.) had drifted from their registered runtime names in `tool_registry` (`get_product_rankings`, `get_category_breakdown`, `get_inventory_overview`).
4. **Architectural Confusion**: `semantic_resolver` was listed as an expected tool in 5 cases, even though semantic resolution in NEXUS is an agent pipeline node (`semantic_node`), not a registered SQL analytics tool.

---

## 3. The Authoritative Canonical Taxonomy

NEXUS defines exactly **12 Authoritative Canonical Intents** in [`backend/app/decisions/taxonomy.py`](file:///c:/Users/rizvi/nexus/backend/app/decisions/taxonomy.py):

| Canonical Intent ID | Name | Analytical Family | Scope & User Goal |
| :--- | :--- | :--- | :--- |
| **`metric_lookup`** | Metric Lookup | Descriptive | Point-in-time lookup or single aggregate metric retrieval over a defined timeframe. |
| **`comparison`** | Comparative Analysis | Comparative | Comparing metrics between two or more time horizons, baselines, or entities. |
| **`trend`** | Timeseries Trend Analysis | Descriptive | Evaluating historical multi-period trajectory or timeseries progression. |
| **`product_analysis`** | Product & Category Analysis | Dimensional | Analyzing product portfolio performance, sales rankings, or categorical breakdowns. |
| **`customer_analysis`** | Customer & Cohort Analysis | Customer Behavior | Evaluating customer retention, RFM segmentation, lifetime value, and cohort behavior. |
| **`inventory_analysis`** | Inventory & Supply Chain | Operational | Evaluating warehouse stock balances, inventory turnover velocity, and reorder signals. |
| **`expense_analysis`** | Operating Expense Analysis | Financial | Tracking overhead, operating expenditures (OPEX), cost of goods sold, and vendor costs. |
| **`diagnostic_analysis`** | Diagnostic & Root-Cause | Diagnostic | Decomposing the underlying causal drivers, variance, or price-volume-mix effects. |
| **`statistical_analysis`** | Statistical Testing & Correlation | Inferential | Formal hypothesis testing, statistical dependence, p-value calculations, and correlation. |
| **`forecasting`** | Predictive Forecasting | Predictive | Generating future time-series projections, confidence intervals, and model metrics. |
| **`semantic_resolution`** | Semantic KPI Resolution | Knowledge | Disambiguating business abbreviations, metric synonyms, company policy, or formulas. |
| **`unsupported`** | Unsupported & Out-of-Scope | None | Inquiries outside the BI boundary, missing datasets, or security adversarial attempts. |

---

## 4. Intent Hierarchy & Subtype Definitions

To preserve fine-grained analytical nuance without fracturing top-level routing, NEXUS implements an explicit two-tier hierarchy:

$$\text{User Query} \longrightarrow \text{Canonical Intent} \longrightarrow \text{Optional Subtype}$$

```
Canonical Intent
├── metric_lookup
│   ├── single_metric
│   └── aggregate_kpi
├── comparison
│   ├── period_comparison
│   ├── product_comparison
│   └── target_baseline_comparison
├── trend
│   └── timeseries_trend
├── product_analysis
│   ├── ranking_lookup
│   ├── category_breakdown
│   └── product_lookup
├── customer_analysis
│   ├── customer_lookup
│   ├── repeat_purchase
│   └── rfm_segmentation
├── inventory_analysis
│   ├── inventory_lookup
│   ├── inventory_status
│   └── turnover_dsi
├── expense_analysis
│   └── expense_breakdown
├── diagnostic_analysis
│   ├── variance_decomposition
│   ├── price_volume_mix
│   └── driver_attribution
├── statistical_analysis
│   ├── correlation
│   └── hypothesis_testing
├── forecasting
│   ├── forecast_lookup
│   └── metric_projection
├── semantic_resolution
│   ├── kpi_definition
│   └── synonym_mapping
└── unsupported
    ├── out_of_scope
    ├── unsupported_metric
    └── security_adversarial
```

---

## 5. Centralized Legacy Compatibility Mapping Layer

All legacy aliases and historical evaluation labels are centralized in `LEGACY_INTENT_MAP` in [`backend/app/decisions/taxonomy.py`](file:///c:/Users/rizvi/nexus/backend/app/decisions/taxonomy.py):

| Legacy Label | Resolved Canonical Intent | Resolved Subtype |
| :--- | :--- | :--- |
| `ranking_lookup` | `product_analysis` | `ranking_lookup` |
| `category_breakdown` | `product_analysis` | `category_breakdown` |
| `product_lookup` | `product_analysis` | `product_lookup` |
| `product_comparison` | `comparison` | `product_comparison` |
| `period_comparison` | `comparison` | `period_comparison` |
| `inventory_lookup` | `inventory_analysis` | `inventory_lookup` |
| `customer_lookup` | `customer_analysis` | `customer_lookup` |
| `forecast_lookup` | `forecasting` | `forecast_lookup` |
| `forecasting_lookup` | `forecasting` | `forecast_lookup` |
| `semantic_resolution` | `semantic_resolution` | `semantic_resolution` |

Calling `resolve_intent(legacy_label)` returns `(canonical_intent, optional_subtype)` with zero string fragmentation across the codebase.

---

## 6. Tool Reconciliation Matrix

Investigation of the 8 tools missing from the Phase 12C report confirmed that all 8 correspond to existing, active runtime tools in `tool_registry`:

| Evaluation Expected Tool | Runtime Registered Tool Name | Classification Status | Architectural Action |
| :--- | :--- | :--- | :--- |
| `get_top_products` | `get_product_rankings` | Renamed Tool | Reconciled in evaluation dataset and `LEGACY_TOOL_MAP` |
| `get_category_performance` | `get_category_breakdown` | Renamed Tool | Reconciled in evaluation dataset and `LEGACY_TOOL_MAP` |
| `get_inventory_status` | `get_inventory_overview` | Renamed Tool | Reconciled in evaluation dataset and `LEGACY_TOOL_MAP` |
| `get_product_velocity` | `get_inventory_velocity` | Renamed Tool | Reconciled in evaluation dataset and `LEGACY_TOOL_MAP` |
| `get_repeat_purchase_rate` | `get_repeat_purchase` | Renamed Tool | Reconciled in evaluation dataset and `LEGACY_TOOL_MAP` |
| `get_customer_metrics` | `get_customer_segments` | Renamed Tool | Reconciled in evaluation dataset and `LEGACY_TOOL_MAP` |
| `run_pvm_decomposition` | `run_price_volume_mix` | Renamed Tool | Reconciled in evaluation dataset and `LEGACY_TOOL_MAP` |
| `semantic_resolver` | *(None / Pipeline Node)* | Pipeline Node Artifact | Semantic resolution is executed by `semantic_node`, not a SQL tool. Reconciled to `[]` tool expectation. |

---

## 7. Evaluation Dataset Reconciliation

In accordance with strict evaluation integrity rules:
1. **Zero Semantic Changes**: No evaluation question was rephrased, altered, or deleted.
2. **Zero Weakening**: All 57 evaluation cases (35 golden, 12 edge cases, 10 adversarial) were retained.
3. **Canonical Field Alignment**:
   - `expected_intent` updated to canonical intent ID.
   - `expected_subtype` added to store fine-grained subtype without overloading primary intent.
   - `expected_tools` updated to registered runtime tool names.
4. **Zero Leakage**: Programmatic check verified 0 token overlap / exact match between the 15 domain exemplars and the 57 evaluation cases.

---

## 8. Benchmark Results: Before vs After Taxonomy Reconciliation

The comparative benchmark was executed across the identical 57 evaluation cases:

| Evaluation Metric | Phase 12C Before Reconciliation | Phase 13 After Taxonomy Reconciliation | Net Change |
| :--- | :---: | :---: | :---: |
| **Intent Questions Evaluated** | 48 | 48 | Identical |
| **Intents in Candidate Enum** | 22 (45.83%) | **48 (100.0%)** | **+54.17% (Complete coverage)** |
| **Intents Missing from Enum** | 26 (54.17%) | **0 (0.0%)** | **Eliminated artificial ceiling** |
| **Intent Routing Accuracy (Jev + Exemplars)**| 45.83% (22/48) | **81.25% (39/48)** | **+35.42%** |
| **Intent Routing Accuracy (Structured LLM)** | 31.25% (15/48) | **64.58% (31/48)** | **+33.33%** |
| **Tool Selection Accuracy (Overall 30 Cases)**| 30.00% (9/30) | **60.00% (18/30)** | **+30.00%** |
| **Tool Selection on Registered Tools** | 90.00% (9/10) | **90.00% (18/20)** | Stable High Precision |
| **Evidence Sufficiency Accuracy** | 100.0% | **100.0%** | 100% Deterministic |
| **Risk Gating Validity** | 100.0% | **100.0%** | 100% Bounded Valid |
| **Candidate Boundary Violations** | 0 | **0** | Zero Boundary Leakage |

---

## 9. Metric Distinction (Disaggregated Breakdown)

To avoid collapsing distinct phenomena into a single score:
- **Primary Intent Accuracy**: 81.25% (Jev + Exemplars), 64.58% (Structured LLM).
- **Subtype Accuracy**: 79.17% (38/48 correct subtype resolution).
- **Tool Selection Accuracy**: 60.00% across all 30 tool cases.
- **Candidate Boundary Violations**: **0 violations (100.0% boundary enforcement)**.
- **Unsupported-Query Detection**: **100.0% (10/10 adversarial and out-of-scope queries detected and rejected)**.

---

## 10. Jev Implications & Production Default

1. **Jev Intent Routing**: With taxonomy reconciliation and domain exemplars, Jev intent routing accuracy rose to **81.25%**. While significantly improved from the zero-shot baseline (27.08%), it has not yet reached the >=95% production threshold.
2. **Production Default Preserved**: `DECISION_PROVIDER=structured_llm` remains the production default. Jev remains an opt-in experimental provider.
3. **No Silent Fallbacks**: Failure semantics remain strict (failures raise explicit errors; never silent fallback).

---

## 11. Remaining Limitations & Recommendations

1. **Sub-Domain Intent Ambiguity**: Queries that combine diagnostic and comparative elements (e.g. *"Did gross profit improve between May and June and what drove the change?"*) require multi-intent decomposition during planning.
2. **Calibration Safeguard**: Jev confidence remains unvalidated on out-of-candidate choices, requiring deterministic safety rules for risk gating.
3. **Next Step**: Now that the intent taxonomy and decision contracts are completely unified and verified, the architecture is ready for Phase 14 (OKF Business Context Architecture).
