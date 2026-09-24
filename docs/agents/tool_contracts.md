# Agent Tool Architecture & Contracts

## Overview

The agent interacts with the underlying database strictly through the `ToolRegistry` (`app.agents.tools.registry.ToolRegistry`). The LLM never writes raw SQL queries, never executes arbitrary Python code, and never accesses database connections directly.

---

## Registered Tools Catalog

| Tool Name | Category | Primary Function | Underlying Method |
|---|---|---|---|
| `get_financial_summary` | Financial | Calculates 12 core financial metrics with period comparisons | `AnalyticsService.get_financial_summary` |
| `get_sales_timeseries` | Descriptive | Chronological metric buckets (daily, weekly, monthly, quarterly) | `AnalyticsService.get_timeseries_analytics` |
| `get_product_rankings` | Product | Transparent product rankings by explicit metric | `AnalyticsService.get_product_rankings` |
| `get_category_breakdown` | Product | Sales and revenue contribution by product category | `AnalyticsService.get_category_breakdown` |
| `get_customer_segments` | Customer | Customer activity and revenue shares across segments | `AnalyticsService.get_customer_segments_breakdown` |
| `get_rfm_analysis` | Customer | Recency, Frequency, Monetary quintile scoring and binning | `AnalyticsService.get_rfm_analysis` |
| `get_cohort_analysis` | Customer | Acquisition cohort retention and spend over subsequent periods | `AnalyticsService.get_cohort_analysis` |
| `get_repeat_purchase` | Customer | Repeat purchase rate, one-time customer ratio, order frequency | `AnalyticsService.get_repeat_purchase_metrics` |
| `get_inventory_overview` | Inventory | Current inventory valuation, out-of-stock items, reorder alerts | `AnalyticsService.get_inventory_overview` |
| `get_inventory_turnover` | Inventory | Inventory turnover ratio and Days Sales of Inventory (DSI) | `AnalyticsService.get_inventory_turnover` |
| `get_inventory_velocity` | Inventory | Fast-moving, slow-moving, and dormant SKU classification | `AnalyticsService.get_inventory_velocity` |
| `get_expense_analytics` | Expenses | Total OPEX, categorical distribution, recurring overhead share | `AnalyticsService.get_expense_analytics` |
| `run_variance_analysis` | Diagnostic | Dissects revenue change across products, categories, or segments | `AnalyticsService.get_variance_analysis` |
| `run_price_volume_mix` | Diagnostic | Mathematical decomposition into Price, Volume, and Mix effects | `AnalyticsService.get_pvm_decomposition` |
| `run_correlation` | Statistics | Pearson / Spearman correlation coefficient and p-value | `AnalyticsService.get_bivariate_correlation` |
| `run_hypothesis_test` | Statistics | Two-sample Welch's t-test comparing customer segment order values | `AnalyticsService.get_hypothesis_test` |

---

## Tool Execution Lifecycle

Every registered tool follows a strict contract:
1. **Input Validation**: Arguments are validated against a dedicated Pydantic input schema (e.g. `FinancialSummaryToolInput`, `VarianceAnalysisToolInput`). Malformed inputs return an error immediately without database execution.
2. **Context Assembly**: Converts validated dates and filters into a strongly-typed `AnalysisContext`.
3. **Deterministic Evaluation**: Calls the corresponding `AnalyticsService` method, running optimized database queries and numerical routines.
4. **Evidence Generation**: Attaches an `EvidenceRecord` declaring tables, columns, formulas, assumptions, and limitations.
5. **Execution Payload**: Returns a `ToolExecutionResult` containing raw results, serialized evidence, timing metrics, and status.

```python
class ToolExecutionResult(BaseModel):
    tool: str
    status: str  # "success" or "error"
    result: Dict[str, Any]
    evidence: Optional[Dict[str, Any]]
    assumptions: List[str]
    limitations: List[str]
    execution_time_ms: float
    error_message: Optional[str]
```
