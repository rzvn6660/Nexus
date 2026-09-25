# NEXUS Experience Audit: Current vs Problem vs New Direction

**Document Version**: 1.0  
**Phase**: Phase 12 Preparation / Transformation  
**Role**: Senior Product Designer + Staff Frontend Engineer + AI Product Architect  
**Objective**: Comprehensive evaluation of the existing NEXUS frontend interface against the core philosophy: *"Where Business Data Becomes Intelligence."*

---

## 1. Executive Summary & Design Principle

NEXUS is not a generic AI chatbot, nor is it a legacy BI dashboard with an AI widget bolted on. Its architectural promise is:
$$\text{Business Data} + \text{Business Context} + \text{Deterministic Analytics} + \text{Agentic Investigation} + \text{Verifiable Evidence} + \text{Human Judgment} = \text{Intelligence}$$

### The Brand Principle: Quiet Intelligence
- **Calm, High-Clarity Visual Canvas**: Deep optical void (`#060911`), structural slate surfaces (`#0F172A`), restrained cyan accents (`#00F2FE`), and electric sky (`#38BDF8`).
- **Precision over Decoration**: Avoid glowing neons, floating 3D brains, sci-fi particle fields, or meaningless animations.
- **Workflow-Centric Architecture**: Replace arbitrary cards with an intuitive progression:
  $$\text{UNDERSTAND} \longrightarrow \text{INVESTIGATE} \longrightarrow \text{VALIDATE} \longrightarrow \text{PREDICT} \longrightarrow \text{DECIDE}$$

---

## 2. Page-by-Page Audit & Directional Blueprint

### A. Global Layout & Shell (`AppShell`, `Sidebar`, `TopBar`)
- **Current State**:
  - Standard 3-part layout: Left sidebar with flat link list, top bar with generic title and search button, center column with stacked cards.
  - Sidebar treats all routes identically (Overview, Analytics, Investigations, Forecasts, Ask, Data, Knowledge).
  - No visual distinction between data sources, operational workflows, and historical decision records.
  - Phase 11's newly implemented persisted history and human review gates are completely inaccessible from the UI.
- **Identified Problems**:
  - Feels like a standard SaaS dashboard rather than a unified *Intelligence Workspace*.
  - No persistent context rail or sense of active business telemetry.
  - Lack of hierarchical navigation grouping (Core Intelligence vs Data Layer vs Knowledge vs Governance).
- **New Direction**:
  - **NEXUS Workspace Architecture**: Reorganize navigation into logical intelligence domains:
    ```
    NEXUS
    ├── Overview (Commercial Telemetry & Briefing)
    ├── Ask (Intelligence Console)
    ├── Investigate (Diagnostic Root-Cause Engine)
    ├── Forecast (Prospective Predictive Modeling)
    │
    ├── DATA
    │   ├── Data Health (Coverage & Quality)
    │   └── Schema Catalog (Tables & Cardinality)
    │
    ├── KNOWLEDGE
    │   ├── Business Context (Corporate Policies & RAG)
    │   └── KPI Dictionary (Semantic Ontology)
    │
    └── HISTORY & GOVERNANCE (Phase 11 Backend Integration)
        ├── Analyses (Persisted Analytical Runs)
        └── Decisions (Human Review Gate & Audit Trail)
    ```
  - **Brand Mark Fidelity**: Integrate the official SVG symbol (`brand/logo/symbol/nexus-symbol.svg`) with optical precision instead of CSS approximations.
  - **Context Rail / Quick Inspector**: Provide seamless slide-out drawer access to evidence, execution latency, and data health status from anywhere in the app.

---

### B. Overview Page (`OverviewPage.tsx`)
- **Current State**:
  - 4 large KPI cards (Revenue, Gross Margin, Total Orders, Average Order Value) followed by Area and Bar charts, product rankings, and signals.
  - Standard dashboard grid reminiscent of Google Analytics or generic admin templates.
- **Identified Problems**:
  - Excessive visual weight given to basic metric numbers without narrative context.
  - Fails to answer the fundamental executive questions: *"What is happening? Why did it happen? What comes next?"*
  - Signals are displayed as generic notification alerts rather than actionable intelligence findings with clear paths to investigation.
- **New Direction**:
  - **NEXUS Intelligence Briefing**:
    - **Eyebrow**: `NEXUS INTELLIGENCE`
    - **Anchor Statement**: *"Understand what is happening. Know why. See what comes next."*
    - **Concise Business State**: An elegant high-density information field (e.g. Net Revenue, Gross Margin, Inventory Health with exceptions) rather than bloated cards.
  - **"What Changed" Section**: Curated observed signals structured as:
    - **WHAT**: The observed metric shift (e.g., *Gross margin contracted 2.3pp*).
    - **WHY IT MATTERS**: The commercial impact (e.g., *Net revenue expanded 8.4%, but supplier acquisition costs increased 14.1%*).
    - **INSPECT**: Direct action triggers: `[Investigate Root Cause]` and `[View SQL Evidence]`.
  - **Continuous Intelligence Flow**: Every chart links directly forward into `[Investigate Why]` and `[Forecast Horizon]`.

---

### C. Ask NEXUS (`AskNexusPage.tsx`)
- **Current State**:
  - Textarea with a chat-bubble-style result list.
  - Responses look like a chatbot transcript.
- **Identified Problems**:
  - Chatbot design lowers perceived intelligence and analytical rigor. Executives and senior analysts do not want a ChatGPT toy; they need structured analytical findings.
  - Responses do not follow a standardized intelligence report format.
- **New Direction**:
  - **Intelligence Console**:
    - Large centered prompt hero: *"What do you want to understand?"*
    - Domain-curated executive prompt pills (margin analysis, growth drivers, predictive horizons, inventory turnover).
  - **Structured Intelligence Report Format**:
    $$\text{INQUIRY} \longrightarrow \text{NEXUS RESOLUTION} \longrightarrow \text{OBSERVED FINDING} \longrightarrow \text{DECOMPOSED DRIVERS} \longrightarrow \text{VERIFIABLE EVIDENCE} \longrightarrow \text{NEXT STRATEGIC ACTION}$$
  - Full display of semantic term resolution (e.g., resolving *"profit"* $\rightarrow$ *Gross Profit*) and temporal boundaries.
  - Clarification prompts rendered cleanly as interactive disambiguation dialogues when questions are underspecified.

---

### D. Diagnostic Investigations (`InvestigationsPage.tsx`)
- **Current State**:
  - Input field followed by observations, hypothesis list, and conclusions.
  - Flat card list for hypotheses.
- **Identified Problems**:
  - The actual multi-step diagnostic progression is hidden in text cards.
  - The hierarchy of problem decomposition (Category $\rightarrow$ Product $\rightarrow$ Price/Volume/Mix $\rightarrow$ Customer) is not visually expressed.
- **New Direction**:
  - **Visual Diagnostic Path (`InvestigationPath`)**:
    - Visual tree layout showing the symptom at root and branching candidate drivers:
      $$\text{Metric Shift} \longrightarrow \text{Category Contribution} \longrightarrow \text{Product Concentration} \longrightarrow \text{Price / Volume / Mix} \longrightarrow \text{Evidence Gate}$$
  - **Strict Four-Tier Epistemic Separation**:
    1. **OBSERVED FACT**: Deterministic historical measurements.
    2. **TESTED HYPOTHESIS**: Candidate explanations tested against data (Confirmed vs Rejected).
    3. **SUPPORTED EVIDENCE**: Row-level lineage, SQL queries, and mathematical proofs.
    4. **CAUSALITY CAVEATS & LIMITATIONS**: Explicit warnings that statistical association is not unconstrained causation.

---

### E. Predictive Forecasting (`ForecastsPage.tsx`)
- **Current State**:
  - Form controls at the top, a ComposedChart with historical and forecast lines, followed by model stats.
- **Identified Problems**:
  - Looks like another generic chart page.
  - Forecast uncertainty is represented only as an area fill without clear visual narrative of expanding horizons and model assumptions.
  - Does not visually articulate why a specific model was chosen over the baseline.
- **New Direction**:
  - **Three-Stage Temporal Narrative**:
    $$\text{WHERE WE WERE (Observed History)} \longrightarrow \text{WHERE WE ARE (Present Boundary)} \longrightarrow \text{WHERE THE MODEL EXPECTS (Prospective Horizon)}$$
  - **Prominent Uncertainty Envelope**: Visual corridor with clear lower/upper bound callouts.
  - **Forecast Quality Scorecard**: Explicit display of expanding-window backtesting metrics:
    - MAE (Mean Absolute Error)
    - RMSE (Root Mean Squared Error)
    - sMAPE (Symmetric Mean Absolute Percentage Error)
    - Baseline Benchmark Comparison (explaining why candidate model outperformed naïve baseline).
  - **Assumptions & Honest Limitations**: Visible boundaries clarifying what external factors (market changes, promotion shifts) cannot be anticipated by the univariate series.

---

### F. Deterministic Analytics (`AnalyticsPage.tsx`)
- **Current State**:
  - Tabs and dropdowns for metrics, time series chart, breakdown tables.
- **Identified Problems**:
  - Feels disconnected from the investigation and forecast flows.
  - Metrics are presented as static tables rather than dynamic intelligence queries.
- **New Direction**:
  - **Continuous Workflow Anchor**:
    $$\text{QUESTION} \longrightarrow \text{DETERMINISTIC METRIC} \longrightarrow \text{RESULT} \longrightarrow \text{INVESTIGATE [Why did this change?]} \longrightarrow \text{FORECAST [What happens next?]}$$
  - High-density precision data tables with direct link to cryptographic evidence.

---

### G. Evidence System (`EvidencePanel.tsx`)
- **Current State**:
  - Modal with formula, row count, execution time, and raw JSON predicates.
- **Identified Problems**:
  - Too technical for executives, slightly unorganized for technical data auditors.
- **New Direction**:
  - **Dual-Perspective Presentation**:
    - **Executive / Business View**: Plain-language justification, formal business definition, data freshness, and policy references.
    - **Analyst Audit View**: Full database lineage (tables, columns, date partitions), executed SQL, row-level filters, execution latency, and SHA-256 cryptographic fingerprint with 1-click verification.

---

### H. Data Health & Catalog (`DataPage.tsx`)
- **Current State**:
  - High-level record counts and table schema viewer.
- **Identified Problems**:
  - Doesn't clearly convey the concept: *"NEXUS knows what it knows."*
- **New Direction**:
  - Four explicit data health postures: `READY`, `READY WITH WARNINGS`, `INSUFFICIENT DATA`, `INVALID`.
  - Comprehensive quality scorecard covering completeness, uniqueness, referential integrity, and freshness.

---

### I. Business Knowledge & Semantic Layer (`KnowledgePage.tsx`)
- **Current State**:
  - Document list and KPI table with an interactive term sandbox.
- **Identified Problems**:
  - Looks like a documentation wiki rather than an enterprise business ontology.
- **New Direction**:
  - Reframe as the **Semantic Ontology & Policy Layer**:
    - Canonical KPI definitions with their formal calculation formulas and enterprise synonyms.
    - Active business policies retrieved via RAG with citation provenance.
    - Live semantic resolution playground demonstrating deterministic mapping from conversational terms to database concepts.

---

### J. Persisted History & Human Decision Review (`HistoryPage.tsx` — NEW in UI)
- **Current State**:
  - Phase 11 implemented real backend database tables (`AnalysisRun`, `DecisionRecord`), migrations, and API endpoints (`/api/v1/history/analyses`, `/api/v1/history/decisions`, `/api/v1/history/decisions/{id}/review`, `/api/v1/history/analyses/{id}/report`).
  - No frontend page or navigation entry exists for these capabilities yet!
- **Identified Problems**:
  - Major V1 capability is invisible to users.
  - The Human-in-the-Loop review gate (`PENDING` $\rightarrow$ `APPROVED` / `REJECTED` / `MODIFIED`) cannot be exercised from the web interface.
- **New Direction**:
  - Build `HistoryPage.tsx` with two dedicated operational views:
    1. **Persisted Analysis History**: Browse past analytical executions, review findings, inspect evidence, and download structured markdown intelligence reports directly from the backend.
    2. **Human Decision Review Gate**: Active recommendation queue where analysts and executives review proposed business actions, inspect reasoning and impact, select `APPROVE`, `REJECT`, or `MODIFY`, provide audit notes, and commit state to the database.

---

## 3. Summary of Transformation Roadmap

| Area | Current Pattern | New NEXUS Pattern |
|---|---|---|
| **Theme & Aesthetic** | Standard Slate UI with random glow | Quiet Intelligence: Deep Void, Precision Lines, Electric Cyan |
| **Navigation** | Flat sidebar list | Hierarchical Workspace (Core, Data, Knowledge, History) |
| **Overview** | KPI card soup + generic charts | Executive Briefing: Business State + What Changed + Inspect |
| **Ask** | Chatbot conversational bubbles | Intelligence Console: Structured Intelligence Reports |
| **Investigation** | Text card list of hypotheses | Visual Diagnostic Path (`InvestigationPath`) + 4-Tier Evidence |
| **Forecast** | Basic chart with filled area | 3-Stage Story + Uncertainty Envelope + Backtest Scorecard |
| **Analytics** | Isolated metric tables | Continuous Flow: Question $\rightarrow$ Metric $\rightarrow$ Investigate $\rightarrow$ Forecast |
| **Evidence** | Monolithic modal | Dual Perspective: Executive View vs Analyst Audit Trace |
| **Human Review** | Missing in UI | Dedicated Governance & Decision Review Gate |
