# NEXUS Phase 14: OKF Business Context Architecture Report

**Commit Baseline**: `95d5d40` (Phase 13: Taxonomy Reconciliation & Decision Architecture Cleanup)  
**Production Decision Provider**: `structured_llm` (Default retained; Jev remains optional/experimental)  
**Test Suite Status**: 289/289 Passing (100% green; 27 new tests added, zero regressions)  
**Phase Status**: Fully Complete

---

## 1. Executive Summary & Core Principle

Phase 14 introduces the **Organizational Knowledge Fabric (OKF)** — an optional, portable business-knowledge representation and synchronization layer for NEXUS.

### The Invariant Boundary: Business Context vs. Empirical Evidence
Business context and empirical evidence serve fundamentally distinct roles in NEXUS:

```
┌─────────────────────────────────────────────────────────────┐
│                 BUSINESS CONTEXT (OKF)                      │
│  Tells NEXUS:                                               │
│  - What terms and acronyms mean in this organization (GP)   │
│  - How KPIs are defined (Gross Profit = Revenue - COGS)     │
│  - What business rules & policies apply (Discount > 20%)    │
│  - What operating calendar & fiscal cycles govern the firm  │
└──────────────────────────────┬──────────────────────────────┘
                               │ Guides interpretation & planning
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                NEXUS AGENTIC CORE ENGINE                    │
│  (Understand → Plan → Validate → Execute → Check → Explain) │
└──────────────────────────────▲──────────────────────────────┘
                               │ Evaluates factual metrics
┌──────────────────────────────┴──────────────────────────────┐
│              ACTUAL DATA & DETERMINISTIC EVIDENCE           │
│  Tells NEXUS:                                               │
│  - What actually happened in the business                   │
│  - How much occurred (exact dollar amounts, units sold)      │
│  - When transactions occurred                               │
│  - Whether a quantitative hypothesis is empirically verified│
└─────────────────────────────────────────────────────────────┘
```

> **CORE PRINCIPLE**:
> Business context defines what the business means, how KPIs are defined, and what policies exist.
> Actual business data and deterministic calculations determine factual evidence.
> **Business context NEVER overrides actual data or deterministic evidence.**

---

## 2. Architecture & Design

OKF is designed as a modular, tenant-neutral subsystem located in `backend/app/knowledge/okf/`:

```
backend/app/knowledge/okf/
├── __init__.py           # Public API exports
├── models.py             # Pydantic schemas (OKFBundle, OKFItem, OKFStatus, OKFItemType)
├── validator.py          # Deterministic pre-persistence bundle validator
├── parser.py             # Markdown + YAML frontmatter parser & deterministic exporter
├── security.py           # Untrusted input sanitizer & prompt injection defense
├── semantic_bridge.py    # Bridge to Phase 13 Canonical Taxonomy & SemanticResolver
└── service.py            # Persistence & RAG synchronization service
```

### Key Architectural Invariants
1. **OKF is Strictly Optional**: NEXUS functions completely without any OKF bundle present (using baseline PostgreSQL data and the default retail ontology). When OKF bundles are provided, NEXUS becomes context-enhanced.
2. **Zero Second Taxonomy**: OKF does not duplicate or compete with the Phase 13 Canonical Intent Taxonomy. Definitional inquiries map directly to `CanonicalIntent.SEMANTIC_RESOLUTION`.
3. **No Code Execution**: OKF does not permit executable code, functions, or shell execution in formulas or metadata. Formulas are strictly declarative mathematical strings.
4. **Deterministic Validation**: Bundles are validated deterministically before hitting the database. Malformed bundles fail safely without corrupting system state.
5. **Conflict Surfacing**: When retrieved business definitions contradict one another (e.g. differing thresholds across policies), NEXUS surfaces the conflict rather than guessing or silently prioritizing one.

---

## 3. Authoritative OKF Schema

The portable representation uses **Markdown with YAML frontmatter**, separating metadata, declarative formulas, provenance, and descriptive prose.

### Supported Entity Types (`OKFItemType`)
- `bundle`: Bundle container metadata and manifest
- `company_profile`: Organizational metadata (industry, currency, fiscal start month)
- `concept`: Business terminology, segment definitions, customer classifications
- `kpi`: Key Performance Indicator specifications, formulas, and synonyms
- `rule`: Declarative operational logic, conditions, and actions
- `policy`: Governance policies, discount ceilings, return windows, approval hierarchies
- `calendar`: Fiscal quarters, peak promotional seasons, and blackout windows

### Example Authoritative Bundle (`retail_core_context_v1`)

```markdown
---
id: retail_core_context_v1
name: Retail Enterprise Context Bundle
type: bundle
version: 1
status: verified
author: Finance & Operations Committee
created_at: 2026-01-01
---

Authoritative business definitions, accounting rules, and operating policies for Retail Corp.

---
id: kpi_gross_profit
name: Gross Profit
type: kpi
version: 1
status: verified
source: corporate_financial_policy_2026
author: Chief Financial Officer
domain: finance
formula: gross_sales - cogs
synonyms:
  - GP
  - gross margin dollars
canonical_intent: metric_lookup
metric_field: gross_profit
unit: currency
target_direction: increase
tags:
  - finance
  - profitability
---

# Gross Profit

Gross Profit measures commercial margin after deducting product cost of goods sold.

---
id: concept_repeat_customer
name: Repeat Customer
type: concept
version: 1
status: verified
source: customer_lifecycle_sop
author: Growth & CRM Team
domain: customer
synonyms:
  - returning buyer
  - loyal shopper
tags:
  - crm
  - retention
---

# Repeat Customer

A repeat customer is defined as any customer account with two or more completed orders.

---
id: policy_discount_ceiling
name: Promotional Discount Ceiling
type: policy
version: 1
status: verified
source: commercial_discount_governance
author: VP Merchandising
domain: merchandising
condition: discount_pct > 0.20
action: require_director_approval
scope: retail_and_wholesale
priority: 10
synonyms:
  - promotional discount
  - discounts over 20%
tags:
  - governance
  - pricing
---

# Promotional Discount Ceiling

Discounts exceeding 20% require formal written authorization from the Merchandising Director.
```

---

## 4. Deterministic Pre-Persistence Validation

The `OKFValidator` deterministically validates bundles prior to any database write.

### Checked Rules
1. **Identifier Format**: Regex `^[a-z0-9][a-z0-9_-]{1,63}$` (lowercase slug, 2-64 chars).
2. **Uniqueness**: Absolute uniqueness of item IDs across the entire bundle.
3. **Lifecycle States**: Enforces valid `OKFStatus` (`verified`, `draft`, `deprecated`).
4. **Provenance & Verification**: Every item must supply a non-empty `source`. Verified items require `author` or `verified_by`.
5. **Temporal Validity**: Ensures `effective_from <= effective_to`.
6. **Referential Integrity**: All IDs listed in `related_to` must exist in the bundle.
7. **Synonym Collision**: Detects intra-bundle collisions where two different items map identical synonyms to incompatible targets.
8. **Prohibited Execution**: Rejects formulas containing `eval`, `exec`, `__import__`, `os.`, `sys.`, `<script>`, or SQL injection keywords.

---

## 5. Persistence Model

Database persistence is implemented using SQLAlchemy 2.0 ORM models in `backend/app/models/okf.py`:

```
┌─────────────────────────────────┐
│          okf_bundles            │
├─────────────────────────────────┤
│ id (PK, int)                    │
│ bundle_id (unique slug, string) │
│ name (string)                   │
│ version (int)                   │
│ status (string)                 │
│ author (string)                 │
│ description (text)              │
│ metadata_json (json)            │
│ created_at / updated_at (tz)    │
└────────────────┬────────────────┘
                 │ 1:N (CASCADE)
                 ▼
┌─────────────────────────────────┐
│           okf_items             │
├─────────────────────────────────┤
│ id (PK, int)                    │
│ bundle_id (FK -> okf_bundles.id)│
│ item_id (string, indexed)       │
│ name (string)                   │
│ item_type (string, indexed)     │
│ version (int)                   │
│ status (string)                 │
│ domain (string, indexed)        │
│ source (string)                 │
│ author / verified_by (string)   │
│ effective_from / to (datetime)  │
│ formula (string, declarative)   │
│ synonyms (json array)           │
│ canonical_intent (string)       │
│ analytics_tool / metric_field   │
│ unit / target_direction         │
│ condition / action / scope      │
│ priority (int)                  │
│ related_ids / tags (json)       │
│ content_markdown (text)         │
│ metadata_json (json)            │
│ created_at / updated_at (tz)    │
└─────────────────────────────────┘
```

Alembic migration `004_phase14_okf_tables.py` manages table provisioning with indices on `(bundle_id, item_id)` and `(domain, item_type)`.

---

## 6. RAG & Semantic Integration

### Synchronization Flow
```
OKF Bundle Text
      │
      ▼
Security Inspection (OKFSecurityFilter)
      │
      ▼
Deterministic Validation (OKFValidator)
      │
      ▼
Normalized Database Persistence (OKFBundleModel, OKFItemModel)
      │
      ▼
RAG Ingestion Sync (_sync_bundle_to_rag)
      ├── Creates KnowledgeDocument (source="okf:<author>")
      └── Creates KnowledgeChunks (tag: is_business_definition=True)
      │
      ▼
Semantic Bridge (OKFSemanticBridge)
      └── Registers synonyms & definitions into runtime KPIOntology
```

### Explicit RAG Distinction
Chunks synchronized from OKF are tagged with `is_business_definition: True` and prefixed:
`[Business Context Definition: <Name>]`.
When retrieved during analysis, the agent presents them as organizational definitions, preserving full separation from empirical `EvidenceRecord`s produced by analytics execution.

---

## 7. Security Model & Untrusted Input Defenses

Business knowledge imports are treated as untrusted input. The `OKFSecurityFilter` enforces five defensive layers:

1. **Prompt Injection Defense**:
   - Scans Markdown and YAML values for instruction override patterns:
     - `ignore previous instructions`
     - `system override`
     - `you are now DAN`
     - `developer mode enabled`
     - `<script>` and `javascript:` URIs
2. **Safe YAML Deserialization**:
   - Uses `yaml.safe_load` exclusively. Disallows custom tags such as `!!python/object/apply`.
3. **Resource Bounds**:
   - Max bundle text size: 2 MB
   - Max items per bundle: 500
   - Max description length: 50,000 characters
4. **Path Traversal Defense**:
   - Rejects file references containing `..` or system root traversals.
5. **Execution Elimination**:
   - Declarative formulas only. Any code execution constructs (`eval`, `exec`, `open`, `__import__`) trigger immediate rejection.

---

## 8. Evaluation Methodology & Measured Results

The evaluation dataset (`evaluation/datasets/okf_evaluation_cases.json`) was executed across 5 distinct operational regimes using `okf_evaluator.py`:

| Operational Regime | Total Cases | Passed | Accuracy | Verified Behavior |
|:---|:---:|:---:|:---:|:---|
| **A. No Business Context (Baseline)** | 3 | 3 | **100.0%** | Standard deterministic analytics execute normally; unknown acronyms safely fail without hallucinating. |
| **B. Valid Business Context (OKF)** | 4 | 4 | **100.0%** | Custom acronyms ("GP") resolve; policy rules and concept definitions answer without unnecessary tool executions. |
| **C. Conflicting Business Context** | 2 | 2 | **100.0%** | Contradictions across documents (e.g. 2 vs 3 orders, 14 vs 30 days return window) are surfaced as explicit ambiguity alerts. |
| **D. Invalid Business Context** | 4 | 4 | **100.0%** | Pre-persistence validator safely rejects duplicate IDs, inverted dates, dangling relations, and colliding synonyms before DB write. |
| **E. Prompt Injection & Adversarial** | 4 | 4 | **100.0%** | System overrides, DAN jailbreaks, unsafe YAML tags, and path traversal payloads are blocked 100%. |

### Aggregate Empirical Metrics
- **Semantic Resolution Precision**: `100.0%`
- **Terminology Mapping Accuracy**: `100.0%`
- **Conflict Surfacing Rate**: `100.0%`
- **Validation Rejection Safety**: `100.0%`
- **Security Injection Block Rate**: `100.0%`
- **Evidence Precedence Preservation**: `100.0%`
- **Hallucination Rate**: `0.0%`

---

## 9. Limitations & Explicit Scope Boundaries

1. **Single-Tenant Neutrality**: OKF in Phase 14 is single-tenant / tenant-neutral. Full multi-tenant workspace isolation is deferred to future enterprise SaaS phases.
2. **Declarative-Only Formulas**: OKF formulas are declarative specifications for human understanding and semantic mapping; they are not an arbitrary expression execution engine.
3. **Optional Nature**: OKF is not mandatory. Organizations without an OKF bundle experience zero degradation in standard analytics, forecasting, or investigation workflows.
4. **Zero Production Decision Provider Change**: `DECISION_PROVIDER=structured_llm` remains the production default. Jev remains optional and experimental.
