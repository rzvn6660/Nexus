# NEXUS Semantic Layer & Business Understanding (Phase 17 Implemented)

## 1. The Core Problem
When non-technical users ask:
> *"What was our total revenue last month?"*

A generic LLM might query `SELECT SUM(total) FROM orders WHERE date ...`.
However, in a real retail business:
- Do "orders" include pending orders?
- Are cancelled orders filtered out?
- Are refunds and return credits deducted?
- Is shipping revenue included or segregated from merchandise revenue?
- Are taxes (VAT/Sales Tax) excluded from top-line revenue?

Leaving metric interpretations to the probabilistic discretion of an LLM creates catastrophic financial discrepancies.

---

## 2. Tenant-Aware Metrics as Code (Phase 17)
In NEXUS, all business definitions are **explicitly defined and stored in the database** per tenant (`TenantSemanticModel`) rather than guessed by an agent:

- **Entity & Dimension Profiling**: Discovers actual mapped records (`Sale`, `Customer`, `Product`, `Inventory`, `Expense`, `SaleItem`).
- **Metric Availability**: Categorizes each metric as `AVAILABLE`, `REQUIRES_COST_DATA`, `INSUFFICIENT_HISTORY`, or `UNAVAILABLE`.
- **Tenant Synonyms & Ambiguity Engine**: Normalizes customer-specific terms (`turnover`, `net sales` -> `revenue`) while halting on bare ambiguous terms like `"sales"` (`"Do you mean revenue, orders, or units sold?"`).
- **Semantic Activation Lifecycle**: Data Gateway ingestion triggers automatic profiling from `NOT_ACTIVATED` -> `ACTIVATING` -> `ACTIVE` or `REQUIRES_REVIEW`.
- **Revision Tracking & Conflict Detection**: Semantic models are versioned monotonically. Competing definitions generate explicit conflicts rather than silent overwrites.

See [tenant_semantic_architecture.md](file:///c:/Users/rizvi/nexus/docs/architecture/tenant_semantic_architecture.md) for full design specifications.

---

## 3. Integration with the Agent Workflow
1. The **Semantic Resolution Node** resolves desired business entities, checks tenant synonym dictionaries, and looks up matching metrics in the tenant's `TenantSemanticModel`.
2. If ambiguity or missing prerequisites are detected, the agent routes to clarification or unsupported handling immediately.
3. The agent cannot invent SQL aggregations for registered KPIs; it is forced to compile the pre-approved calculation definition into the generated database query.
4. Every analytical response explicitly attaches semantic provenance to evidence:
   - Metric name, canonical KPI, definition, calculation, source data, and availability.
