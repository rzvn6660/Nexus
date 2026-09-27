# Phase 17 — Production Business Understanding & Tenant-Aware Semantic Architecture

## 1. Overview
NEXUS Phase 17 activates persistent, tenant-specific Business Understanding and semantic modeling. When customer data is uploaded via the Data Gateway and mapped, NEXUS automatically profiles the business's actual database state, records entity existence and date horizons, determines metric availability, resolves tenant-specific synonyms and ambiguous phrasing, tracks semantic revisions, and grounds all downstream agent calculations strictly in deterministic SQL evidence.

```
DATA GATEWAY (CSV/XLSX)
          ↓
  DATASET PROFILING
          ↓
    SCHEMA MAPPING
          ↓
DATASET READY (INGESTED)
          ↓
TENANT SEMANTIC ACTIVATION (TenantSemanticService.audit_business_understanding)
          ↓
PERSISTENT TENANT SEMANTIC MODEL (TenantSemanticModel v1, v2...)
          ↓
BUSINESS UNDERSTANDING READY (Entities, Metrics, Dimensions, Summary, Coverage)
          ↓
AGENT PIPELINE (Semantic Resolution Node -> Ambiguity Check -> Deterministic Analytics -> Provenance Evidence)
```

---

## 2. Business Understanding Architecture
The Business Understanding layer inspects actual mapped database records for the authenticated tenant (`business_id`):
- **Entities**:
  - `Sale`: Count, date range (`min_date`, `max_date`), available fields (`total_amount`, `discount_amount`, `payment_method`, etc.).
  - `Customer`: Count, customer segments, registration date range.
  - `Product`: Count, categories, unit cost coverage check.
  - `Inventory`: Count, stock levels, warehouse coverage.
  - `Expense`: Count, categories, date range.
  - `SaleItem`: Count, quantity and subtotal coverage (scoped by `Sale.business_id`).
- **Measures & Dimensions**:
  - Quantitative metrics (`total_amount`, `quantity`, `unit_cost`, `stock_level`, `amount`).
  - Dimensions (`product_category`, `payment_method`, `customer_segment`, `expense_category`).
  - Temporal fields (`sale_date`, `acquisition_date`, `expense_date`).
- **Data Quality Warnings**:
  - Highlights missing or incomplete dimensions (e.g. Products missing unit cost prevents Gross Margin; historical span < 60 days prevents Customer Retention).
- **Deterministic Business Summary**:
  - Formatted overview of actual database record counts and date coverage horizons (zero LLM arithmetic).

---

## 3. Persistent Tenant Semantic Model
Each organization and business maintains versioned semantic models stored in table `tenant_semantic_models`:
- `id`: UUID primary key.
- `organization_id`: Foreign key to `organizations.id`.
- `business_id`: Foreign key to `businesses.id`.
- `version`: Integer revision tracker (1, 2, 3...).
- `status`: Lifecycle state (`NOT_ACTIVATED`, `ACTIVATING`, `ACTIVE`, `REQUIRES_REVIEW`, `FAILED`).
- `source_dataset_id`: Optional pointer to the dataset triggering this revision.
- `entities`: JSON map of detected entity metadata.
- `metrics`: JSON map of tenant-specific metric definitions and their availability status.
- `dimensions`: JSON map of categorized dimensions.
- `synonyms`: JSON dictionary of tenant-specific terms mapped to canonical concepts.
- `ambiguous_terms`: JSON map of terms that require disambiguation when requested without qualifying context.
- `business_summary`: Deterministic summary payload.
- `conflicts`: JSON array of competing definition conflicts requiring human resolution.

---

## 4. KPI Availability & Tenant Metric Definitions
Metrics are evaluated against actual mapped columns and data prerequisites:
| Metric | Formula | Required Entities & Fields | Availability State |
|---|---|---|---|
| **Revenue** | `SUM(Sale.total_amount)` | `Sale.total_amount` | `AVAILABLE` or `UNAVAILABLE` |
| **Orders** | `COUNT(Sale.id)` | `Sale.id` | `AVAILABLE` or `UNAVAILABLE` |
| **Units Sold** | `SUM(SaleItem.quantity)` | `SaleItem.quantity` | `AVAILABLE` or `UNAVAILABLE` |
| **Average Order Value** | `SUM(Sale.total_amount) / COUNT(Sale.id)` | `Sale.total_amount`, `Sale.id` | `AVAILABLE` or `UNAVAILABLE` |
| **Gross Margin** | `(Revenue - Cost) / Revenue` | `Product.unit_cost`, `SaleItem` | `AVAILABLE` or `REQUIRES_COST_DATA` |
| **Inventory Value** | `SUM(stock_level * unit_cost)` | `Inventory`, `Product.unit_cost` | `AVAILABLE` or `UNAVAILABLE` |
| **Customer Count** | `COUNT(Customer.id)` | `Customer.id` | `AVAILABLE` or `UNAVAILABLE` |
| **Expense** | `SUM(Expense.amount)` | `Expense.amount` | `AVAILABLE` or `UNAVAILABLE` |
| **Customer Retention** | Returning customer ratio | `Sale.customer_id`, `Sale.sale_date` (span >= 60d) | `AVAILABLE` or `INSUFFICIENT_HISTORY` |

---

## 5. Synonyms & Disambiguation Engine
Tenants can define business-specific vocabulary:
- **Synonyms**:
  - `"turnover"`, `"net sales"`, `"top line"` → Canonical `revenue`.
  - `"client"`, `"buyer"`, `"patron"`, `"account"` → Canonical `customer`.
  - `"cost of sales"`, `"expenditures"`, `"overheads"` → Canonical `expense`.
- **Ambiguity Detection**:
  - The term `"sales"` can ambiguously signify `revenue` (monetary amount), `orders` (transaction count), or `units_sold` (volume of items).
  - When a query contains a bare ambiguous term without qualifying context (e.g., *"How did sales perform?"*), the resolver returns `requires_clarification: true` with options `["revenue", "orders", "units_sold"]`.
  - If a qualifier or registered multi-word synonym exists (e.g., *"what was our total sales revenue?"* or *"number of sales"*), the engine determines the explicit canonical target without unnecessary clarification.

---

## 6. Business Context Integration & Conflict Handling
- Integrates with the Phase 14 Organizational Knowledge Framework (OKF).
- Business context explains policies, operational calendars, and terminology.
- **Strict Boundary**: Business context is advisory. It **never overrides deterministic evidence** or executes arithmetic.
- **Conflict Handling**: When a new dataset or document proposes a metric definition conflicting with an established active model (e.g., Gross Sales vs Net Sales after returns), the system flags the semantic model as `REQUIRES_REVIEW` and records the competing definitions in `conflicts`. It never silently overwrites existing corporate definitions.

---

## 7. Semantic Activation Lifecycle
1. `NOT_ACTIVATED`: No datasets mapped or activated yet.
2. `ACTIVATING`: Data Gateway ingestion job completed; `TenantSemanticService.audit_business_understanding` initiates profiling.
3. `ACTIVE`: Audit successfully completed; metric availabilities, entities, and business data summary stored.
4. `REQUIRES_REVIEW`: Semantic conflict or ambiguous mapping requires human confirmation.
5. `FAILED`: System error during semantic profiling; errors are logged and status is preserved.

---

## 8. Versioning & Provenance Traceability
- Every semantic activation creates a new monotonic `version` for the business (`(business_id, version)` unique).
- Historical semantic configurations are immutable, ensuring past answers can be verified against the exact business understanding active at that time.
- **Evidence Provenance**: When an analytics tool executes, `execution_node` decorates the evidence object with:
  ```json
  {
    "semantic_provenance": {
      "canonical_kpi": "revenue",
      "metric_name": "Revenue",
      "semantic_definition": "Sale.total_amount",
      "source_data": "Sales dataset",
      "calculation_definition": "SUM(Sale.total_amount)",
      "semantic_availability": "AVAILABLE"
    }
  }
  ```

---

## 9. Agent Pipeline Integration
In `semantic_resolution_node`:
1. Tenant context (`business_id`, active `TenantSemanticModel`) is resolved from DB.
2. User query is analyzed via `TenantSemanticService.resolve_query`.
3. If clarification is needed, the pipeline halts immediately, routing to `handle_clarification` and prompting the user with deterministic options.
4. If a requested metric is `UNAVAILABLE`, `REQUIRES_COST_DATA`, or `INSUFFICIENT_HISTORY`, the agent stops and routes to `handle_unsupported`, informing the user of the exact missing data prerequisite.
5. If available, the resolved canonical KPI and its formula are injected into the agent state, allowing deterministic analytics tools to execute the exact approved SQL query.
