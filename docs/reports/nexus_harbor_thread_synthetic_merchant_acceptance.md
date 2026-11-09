# NEXUS — Harbor & Thread: Complete Synthetic Merchant Acceptance & End-to-End Pilot Simulation Report

**Date:** November 8, 2026
**Environment:** Local Staging Multi-Container Docker (`nexus_postgres_staging`, `nexus_backend_staging`, `nexus_frontend_staging`, `nexus_redis_staging`, `nexus_mailpit_local`)
**Workspace:** `C:\Users\rizvi\nexus`
**Git Branch:** `feat/phase1g-watermark-migration-rehearsal`
**Execution Type:** Deterministic Synthetic Pilot Simulation & Acceptance Verification

---

> [!IMPORTANT]
> **GOVERNANCE & SYNTHETIC DEMONSTRATION NOTICE**
> All merchant entities, transactions, financial metrics, customer profiles, and consent attestations referenced herein are **100% fictional and deterministically generated** for product validation and simulation purposes.
> **No genuine merchant, individual, legal agreement, consent, or commercial transaction is represented.**
> Status Classification:
> - **ACCEPTED FOR SYNTHETIC DEMONSTRATION** (All synthetic validation invariants, HITL workflows, Playwright downloads, and security boundary tests satisfied).
> - **REAL MERCHANT VALIDATION PENDING** (Real external credentials, live Shopify/Stripe OAuth sync, bank-settled AED transactions, and audited statutory GAAP accounting remain uncertified).

---

## 1. Merchant Profile & Simulated Onboarding Narrative

### 1.1 Commercial Entity Profile
- **Commercial Entity:** Harbor & Thread — NEXUS Synthetic Pilot
- **Legal Entity ID (UUID):** `a65c59f1-d1c1-47c3-8cf5-f8987c28efa3`
- **Parent Organization:** Harbor & Thread Retail Group (`1628e698-5ca3-4358-80ce-2907bc3fd298`)
- **Industry & Vertical:** Premium Fashion, Resort-wear & Lifestyle Retail
- **Operational Geography:** Dubai, United Arab Emirates (UAE)
- **Primary Operational Currency:** AED (United Arab Emirates Dirham)
- **Statutory Taxation Model:** 5.0% UAE Federal Value-Added Tax (VAT)
- **Active Sales Channels (3 Total):**
  1. `Dubai Mall Flagship Store` (Physical Boutique, Fashion Avenue)
  2. `Mall of the Emirates Boutique` (Physical Boutique)
  3. `Online Webstore (harbor-thread.ae)` (Digital Direct-to-Consumer Channel)
- **Fictional Merchant Principal / Owner:** Daniel Morgan
- **Designated Role:** Owner & Commercial Director
- **Demo Credentials:**
  - Email: `daniel.morgan@harbor-thread.local`
  - Password: `[CONFIGURED SECURE PILOT CREDENTIAL]`
  - Auth Scope: Tenant-scoped to Harbor & Thread (`a65c59f1-d1c1-47c3-8cf5-f8987c28efa3`) only.

### 1.2 Simulated Merchant Onboarding & Simulated Consent Workflow
Daniel Morgan was simulated walking through the NEXUS Onboarding experience:
1. **Interactive Guided Assessment:** Business profile, sales channel enumeration, and multi-location setup.
2. **Explicit Simulated Consent Attestation:**
   - **Consent Token:** `SIMULATED_CONSENT_HT_2026_PILOT`
   - **Attestation Scope:** Read-only historical transaction ingestion, algorithmic cadence analysis, prescriptive retention drafting, and executive briefing distribution.
   - **Governance Ledger Record:** Persisted in `decision_records` (ID: `16`) and audited in `decision_audit_events` with timestamp, client IP `127.0.0.1`, actor `daniel.morgan@harbor-thread.local`, and metadata clearly flagging `simulated_demonstration=true`.
3. **Pre-Ingestion Schema Validation:** Ingestion preview displaying row counts, date boundaries, column types, and synthetic COGS labeling before committing any transaction records to the relational store.

---

## 2. Deterministic Dataset Methodology & Mathematical Invariants

### 2.1 Dataset Parameters
- **Deterministic Generator:** `backend/app/analytics/onboarding/harbor_thread_generator.py`
- **Deterministic Seed:** `4200` (100% reproducible across environments)
- **Historical Horizon:** 24 continuous calendar months (November 1, 2024 to October 31, 2026)
- **Customer Population (1,200 Unique Profiles across 10 Dubai Neighborhoods):**
  - **VIP Repeat Cohort (100 customers):** High frequency (18–28 orders), high AOV (AED 1,800–3,200), Downtown Dubai / Palm Jumeirah / Emirates Hills.
  - **Regular Repeat Cohort (350 customers):** Consistent cadence (10–16 orders), Dubai Marina / JBR / DIFC.
  - **At-Risk Repeat Cohort (150 customers):** Prolonged purchase gap (cadence ratio > 2.0x), previously frequent buyers now decelerating.
  - **Lapsed Repeat Cohort (200 customers):** Severe purchase gap (cadence ratio > 3.0x), last transaction > 180 days ago.
  - **Reactivated Cohort (100 customers):** Formerly dormant customers with recent fall 2026 orders.
  - **Single-Order / One-Time Cohort (300 customers):** Exactly 1 historical order (unscored cadence cohort, eligible for onboarding nurture).
- **Product Catalog (180 SKUs across 6 Merchandising Categories):**
  - Categories: *Pure Linen Collection*, *Tailored Suiting & Formalwear*, *Mulberry Silk & Evening*, *Footwear & Leather Goods*, *Fine Accessories*, *Artisanal Fragrance*.
  - Unit Price Range: AED 140.00 – AED 3,200.00.
  - Synthetic Labeled COGS: Explicitly labeled synthetic cost (38%–44% cost ratio).
- **Transaction Scale:**
  - Total Orders Generated & Ingested: **7,808 completed sales**
  - Total Line Items Generated & Ingested: **16,264 individual line items**
  - Gross Transaction Volume: **AED 12,147,386.34**
  - Average Order Value: **AED 1,555.76**
- **Dubai Seasonality Calibration:**
  - **December & January:** Dubai Shopping Festival (DSF) surge (+45% volume).
  - **March / April:** Eid-al-Fitr gift shopping surge (+35% volume).
  - **July & August:** UAE summer heat travel slump (-30% physical store volume, slight online compensation).
  - **September & October:** Autumn luxury resort wear collection launch (+25% volume).

### 2.2 Mathematical Reconciliation & Zero-Tolerance Invariants
Every generated and ingested transaction strictly passed the 4 core financial invariants with zero discrepancies across all 7,808 records:
1. **Line Total Invariant:**
   $$\text{line\_total} = (\text{quantity} \times \text{unit\_price}) - \text{item\_discount}$$
2. **Order Subtotal Invariant:**
   $$\text{subtotal} = \sum_{i=1}^{n} \text{line\_total}_i$$
3. **Statutory Tax Invariant (5% UAE VAT):**
   $$\text{tax\_amount} = \text{round}((\text{subtotal} - \text{order\_discount}) \times 0.05, 2)$$
4. **Order Grand Total Invariant:**
   $$\text{total\_amount} = \text{subtotal} - \text{order\_discount} + \text{tax\_amount}$$

*Audit Result:* **7,808 / 7,808 orders reconciled (100.0% invariant compliance, 0 discrepancies).**

---

## 3. Data Governance, Ingestion Safeguards & Tenant Isolation

### 3.1 Pre-Ingestion Quarantine & Atomic Rollback Verification
Before staging production data, the ingestion pipeline was subjected to negative adversarial validation:
- **Quarantine Probe:** Submitting a batch with malformed telephone strings and unparseable date formats resulted in immediate quarantine segregation. Malformed records were written to quarantine storage without polluting core relational tables or crashing the ingestion runner.
- **Atomic Rollback Probe:** Injecting an unhandled foreign-key violation mid-batch triggered an immediate database rollback. Zero partial batch records leaked into the `sales` or `sale_items` tables.

### 3.2 Authoritative Watermark & Provenance Governance
- **Ingestion Watermark:** Recorded with status `provisional`, watermark boundary `2026-10-31 23:59:59 UTC`, and provenance classification `DEMO_SYNTHETIC`.
- **Policy Enforcement (`TenantCertificationPolicy`):**
  - Any merchant name or token containing terms such as `["sandbox", "synthetic", "pilot", "demo", "mock", "test"]` is prevented from certifying production financial close.
  - Attempts to supply synthetic tokens to production validation endpoints trigger policy rejections.

### 3.3 Multi-Tenant Cryptographic & Logical Boundary Isolation
NEXUS preserves complete multi-tenant boundary isolation between merchants:
- **Isolated Tenants in Staging Database:**
  1. `Northstar Fashion & Retail — NEXUS Sandbox` (`70a53a1b-27c0-4980-92ba-6cbe315c626d`) — Sarah Jenkins
  2. `Apex Specialty Commerce` (`ab044b1a-835a-4a38-bf45-62fe38624151`) — Staging Baseline
  3. `Harbor & Thread — NEXUS Synthetic Pilot` (`a65c59f1-d1c1-47c3-8cf5-f8987c28efa3`) — Daniel Morgan
- **Security Boundary Test Results:**
  - **Unauthenticated Access (No Bearer Token):** `HTTP 401 Unauthorized`.
  - **Cross-Tenant IDOR Attack (Sarah Jenkins attempting to download Daniel Morgan's PDF):** `HTTP 403 Forbidden`.
  - **Missing / Random UUID Report Lookup:** `HTTP 404 Not Found`.

---

## 4. Analytical Intelligence & Human-in-the-Loop (HITL) Decisions

### 4.1 Customer Cadence & Churn Intelligence
NEXUS evaluated the 1,200 Harbor & Thread customer base against empirical inter-purchase intervals:
- **Total Registered Accounts:** 1,200
- **Unscored Cohort (Single-Order Buyers, < 2 order dates):** 288 (24.0%)
- **Scored Repeat Cohort:** 899 (76.0%)
- **Cadence Risk Distribution:**
  - **Low / On Schedule (Ratio < 1.3x):** 299 customers (33.3%)
  - **Watchlist / Medium (1.3x $\le$ Ratio < 2.0x):** 88 customers (9.8%)
  - **High Urgency (2.0x $\le$ Ratio < 3.0x):** 91 customers (10.1%)
  - **Critical Urgency (Ratio $\ge$ 3.0x):** 421 customers (46.8%)
- **Estimated Customer Spend Exposure at Risk:** **AED 4,163,828.80**
- **Observational Invariant Note:** Prolonged purchase intervals in non-contractual fashion retail reflect purchasing cadence deceleration and seasonality, not formal contractual cancellation.

### 4.2 Human-in-the-Loop Retention Decisions
Daniel Morgan reviewed two algorithmic retention interventions generated by NEXUS:
1. **Decision Record 1 (APPROVED):**
   - **Target Cohort:** Critical-risk VIP buyers in Downtown Dubai & Palm Jumeirah.
   - **Intervention:** Private styling consultation at Dubai Mall Store with an exclusive 15% concierge seasonal preview reward.
   - **Action:** Approved by Daniel Morgan (`daniel.morgan@harbor-thread.local`).
   - **Audit Record:** Persisted in `decision_audit_events` with revision 1, state `APPROVED`.
2. **Decision Record 2 (REJECTED):**
   - **Target Cohort:** General at-risk repeat buyers.
   - **Intervention:** 40% blanket flash discount via WhatsApp blast.
   - **Action:** Rejected by Daniel Morgan (`daniel.morgan@harbor-thread.local`) on grounds of luxury brand equity erosion.
   - **Audit Record:** Persisted in `decision_audit_events` with revision 1, state `REJECTED`.

### 4.3 Analyst Studio 8-Domain Verification
The complete Analyst Studio multi-domain engine was executed against Harbor & Thread data:
1. **Descriptive Domain:** Ingested 7,808 sales, AED 12.14M volume, AOV AED 1,555.76.
2. **Diagnostic Domain:** Identified UAE summer slump and category shift toward linen and silk.
3. **Predictive Domain:** Forecasted Q4 holiday and DSF acceleration.
4. **Prescriptive Domain:** Formulated bespoke high-value customer retention proposals.
5. **Exploratory Domain:** Analyzed cross-basket affinity between suiting and leather footwear.
6. **Benchmarking Domain:** Evaluated 61.0% modeled margin against premium boutique peers.
7. **Risk Domain:** Quantified AED 4.16M churn exposure across decelerated repeat buyers.
8. **Audit Domain:** Verified deterministic provenance and zero data tampering.

---

## 5. Pulse Executive Report & Playwright Browser Acceptance

### 5.1 Report Generation & Cryptographic Integrity
- **Target Report:** `[DEMO SYNTHETIC] Harbor & Thread — October 2026 Executive Performance (AED)`
- **Report ID:** `2ee8ee15-1bbb-4e7e-b53c-ad2f81497259`
- **Period Window:** October 1, 2026 to October 31, 2026
- **Monthly Sales (October 2026):** AED 282,334.98 across 186 orders
- **Monthly AOV:** AED 1,517.93 (+17.1% vs prior baseline)
- **Active Customers:** 185 accounts (100% repeat buyers in window)
- **Modeled Gross Margin:** `61.0% [ESTIMATED - synthetic_labeled_costs]`
- **ReportLab PDF Byte Length:** **9,095 bytes**
- **ReportLab PDF SHA-256 Digest:**
  `e6196f59d96fba61e11317e8c0e9959ea2de9f8f69bdb947f0c193c1ab21cc24`

### 5.2 Playwright Browser Automation Results (`run_harbor_thread_browser_acceptance.py`)
A full headless Chromium browser test executed the entire end-to-end user journey:
1. **Manager UI Login:** Logged into `http://127.0.0.1:3001/login` as Daniel Morgan. Token and business ID verified in browser `localStorage`.
2. **Dashboard Review:** Captured screenshot `scratch/screenshots/harbor_thread_01_dashboard.png`.
3. **Pulse Navigation:** Navigated to `/pulse`, switched to `Reports & Publications` tab. Captured screenshot `scratch/screenshots/harbor_thread_02_reports_tab.png`.
4. **Table Row PDF Download:** Clicked `button[title='Download ReportLab PDF']`. Downloaded file to `scratch/harbor_thread_browser_table.pdf`.
5. **Detail Preview Modal PDF Download:** Clicked `button[title='View structured digital report']`. Opened detail modal, captured screenshot `scratch/screenshots/harbor_thread_03_modal_preview.png`. Clicked `Download PDF` inside modal. Downloaded file to `scratch/harbor_thread_browser_modal.pdf`.
6. **Retention UI Review:** Navigated to `/retention`. Captured screenshot `scratch/screenshots/harbor_thread_04_retention.png`.
7. **Cryptographic Binary Validation:**
   - Table download size: **9,095 bytes** | SHA-256: `e6196f59d96fba61e11317e8c0e9959ea2de9f8f69bdb947f0c193c1ab21cc24` (Exact DB Match).
   - Modal download size: **9,095 bytes** | SHA-256: `e6196f59d96fba61e11317e8c0e9959ea2de9f8f69bdb947f0c193c1ab21cc24` (Exact DB Match).
8. **Deep Text Inspection (`pypdf`):**
   - Confirmed banner: `*** SYNTHETIC DEMONSTRATION — NOT REAL MERCHANT DATA — NOT FOR OFFICIAL FINANCIAL AUDIT ***`
   - Confirmed tenant: `Harbor & Thread — NEXUS Synthetic Pilot`
   - Confirmed currency formatting: `AED 282,334.98`, `AED 1,517.93`, `AED 3,938,854.54`
   - Confirmed gross margin estimation label: `[ESTIMATED - synthetic_labeled_costs]` and disclosure `Gross margin figures labeled [ESTIMATED] are modeled using catalog-average-markup across unit cost benchmarks. They do not constitute actual audited accounting profitability`.

---

## 6. Consolidated Verification Matrix & Test Summary

| Test Area / Verification Suite | Execution Command | Result | Duration | Notes |
|:---|:---|:---:|:---:|:---|
| **Synthetic Pilot Acceptance Suite** | `pytest backend/tests/test_harbor_thread_synthetic_pilot_acceptance.py -v` | **10 / 10 PASSED** | 15.53s | Provisioning, consent, quarantine, ingestion, invariants, retention, pulse, 8 domains, Mailpit |
| **Sandbox Regression Suite** | `pytest backend/tests/test_sandbox_merchant_end_to_end_validation.py -v` | **10 / 10 PASSED** | 5.59s | Northstar Fashion & Retail sandbox remains fully operational and unharmed |
| **Browser UI & Security Suite** | `python scratch/run_harbor_thread_browser_acceptance.py` | **PASSED** | 48.2s | Daniel Morgan login, table & modal PDF downloads, SHA-256 check, 401/403/404 security checks |
| **Frontend TypeScript Check** | `npm --prefix frontend run type-check` (`tsc --noEmit`) | **PASSED** | 12.1s | 0 TypeScript errors |
| **Frontend Production Build** | `npm --prefix frontend run build` (`vite build`) | **PASSED** | 22.5s | 2,336 modules transformed, production bundles generated |
| **Backend System Health** | `curl -s http://127.0.0.1:8001/api/health/ready` | **200 OK** | < 0.1s | DB latency 20.39ms, Redis connected |

---

## 7. Operational Environment Status

All staging infrastructure services are active, healthy, and isolated:
- **Backend API:** `http://127.0.0.1:8001` (`nexus_backend_staging`, healthy)
- **Frontend SPA:** `http://127.0.0.1:3001` (`nexus_frontend_staging`, healthy)
- **PostgreSQL Database:** `127.0.0.1:5433/nexus_staging_db` (`nexus_postgres_staging`, healthy)
- **Redis Cache & State:** `127.0.0.1:6380` (`nexus_redis_staging`, healthy)
- **Mailpit SMTP & Web UI:** `127.0.0.1:8025` (Web UI), `127.0.0.1:1025` (SMTP) (`nexus_mailpit_local`, healthy)
- **Background Scheduler:** `nexus_scheduler_staging` (healthy)

---

## 8. Final Verdict & Acceptance Decision

```
========================================================================================
FINAL ACCEPTANCE VERDICT:
----------------------------------------------------------------------------------------
[✓] ACCEPTED FOR SYNTHETIC DEMONSTRATION
    - All synthetic merchant onboarding workflows, deterministic 24-month data generation,
      Dubai VAT financial invariants, HITL decision governance, ReportLab PDF generation,
      browser-driven PDF downloads, and multi-tenant security gates are fully verified.

[ ] REAL MERCHANT VALIDATION PENDING
    - Live merchant credentials, statutory production period-close certification,
      bank-cleared settlements, and audited GAAP financials remain uncertified.
========================================================================================
```
