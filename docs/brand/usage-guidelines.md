# NEXUS Usage Guidelines

**Document Version**: 1.0  
**Status**: Official Brand Specification  
**Classification**: Brand Execution & Media Standards  

---

## 1. Digital & Web Specifications

### Website Hero Section
- **Headline**: `"Where Business Data Becomes Intelligence."`
- **Sub-headline / Paragraph**:
  > *"NEXUS connects business data, corporate context, deterministic analytics, diagnostic investigation, and calibrated forecasting into an evidence-backed intelligence workflow built to help leaders make better-informed decisions."*
- **Primary Hero Visual**:
  - Central display of `brand/logo/symbol/nexus-symbol.svg` at 128px with radial lens glow (`#00F2FE` at 0.15 opacity).
  - Flanked by an interactive pipeline node diagram showing real-time stage progression:  
    `Data ──► Understand ──► Check ──► Analyze ──► Investigate ──► Predict ──► Decide`.
- **Primary Call to Action (CTA)**:
  - Button 1: `"Explore NEXUS"` (`bg-sky-600 hover:bg-sky-500 text-white font-medium px-6 py-3 rounded-lg`)
  - Button 2: `"View Architecture"` (`bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-6 py-3 rounded-lg`)

### Social Media & OpenGraph Assets
- **LinkedIn / Social Card (`brand/social/nexus-social-card.svg`)**:
  - Dimensions: 1200 × 630 px (Standard 1.91:1 aspect ratio).
  - Background: Nexus Void (`#060911`) with subtle dot matrix grid.
  - Content: Primary horizontal logo, official tagline, key value proposition badge, and three feature pill tags (`Deterministic Analytics`, `Diagnostic Investigation`, `Predictive Intelligence`).
- **GitHub Repository Avatar (`brand/github/nexus-github-avatar.svg`)**:
  - Dimensions: 400 × 400 px (1:1 square).
  - Canvas: Centered symbol on `#060911` with 1px border (`#1E293B`) and subtle inner radial glow.
- **GitHub README Banner (`brand/github/nexus-readme-banner.svg`)**:
  - Dimensions: 1280 × 480 px.
  - Content: Large vector mark, tagline, pipeline visualization, and evaluation score badges (`96.5% Intent Accuracy`, `0% Hallucination`, `100% Deterministic`).

---

## 2. Technical Presentation System (Slide Deck Architecture)

When presenting NEXUS to executives, architects, or recruiters, use the following standardized 9-slide visual structure:

```
PRESENTATION SLIDE FLOW
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  01. TITLE   ├────►│ 02. PROBLEM  ├────►│  03. PIPELINE│
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │
       ▼                    ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│04. ENGINE/SQL├────►│05. DIAGNOSTIC├────►│ 06. FORECAST │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │
       ▼                    ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│07. EVALUATION├────►│08. PRODUCTION├────►│ 09. DECISION │
└──────────────┘     └──────────────┘     └──────────────┘
```

1. **Slide 01 — Title & Identity**:
   - Master mark centered over void slate canvas.
   - Title: `NEXUS`
   - Subtitle: `Agentic Business Intelligence Platform`
   - Tagline: `"Where Business Data Becomes Intelligence."`
2. **Slide 02 — The Problem (The "Why" Gap)**:
   - Split view: Static dashboard on the left ("Shows what happened"); ad-hoc analyst queue on the right ("Takes days to answer why").
3. **Slide 03 — The Architecture & Intelligence Pipeline**:
   - High-level block diagram: FastAPI backend, LangGraph state machine, PostgreSQL/pgvector store, and Next.js frontend.
4. **Slide 04 — Deterministic Analytics & Semantic Layer**:
   - SQL generation proof, domain ontology mapping, and 0% arithmetic hallucination guarantee.
5. **Slide 05 — Diagnostic Investigation**:
   - Causal waterfall decomposition: Price, Volume, Mix variance isolating root causes of margin shifts.
6. **Slide 06 — Calibrated Predictive Intelligence**:
   - Multi-horizon forecasting chart with P10/P50/P90 prediction intervals and backtest accuracy metrics.
7. **Slide 07 — Comprehensive Evaluation (Phase 9 Benchmarks)**:
   - 57 evaluation cases across 10 dimensions: 96.5% Intent, 100% Adversarial Defense, 0% Hallucination.
8. **Slide 08 — Production Deployment (Phase 10 Topology)**:
   - Containerized deployment with Docker Compose, health check probes, structured JSON logging, and Prometheus-ready metrics.
9. **Slide 09 — The Conclusion (Human-Centered Intelligence)**:
   - Final takeaway: *"AI augments analysts. AI does not replace human judgment."*

---

## 3. Case Study Visual Framework

Every published NEXUS case study follows a strict 7-phase empirical structure to maintain analytical credibility:

```
CASE STUDY TEMPLATE
┌───────────────────────┬────────────────────────────────────────────────────────┐
│ Phase                 │ Content & Display Standard                             │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ 1. Business Question  │ The raw executive query in bold Inter Display          │
│                       │ e.g. "Why did European enterprise gross margins fall?" │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ 2. Data Health Check  │ Automated verification badge: Row count, null rates,   │
│                       │ temporal boundary validation.                          │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ 3. Deterministic SQL  │ Executed SQL query with runtime in milliseconds and   │
│                       │ exact database tables scanned.                         │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ 4. Investigation      │ Mathematical decomposition isolating Price vs Volume  │
│                       │ vs Mix variance.                                       │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ 5. Context RAG Proof  │ Cited corporate policy excerpt (§4.2 discount rules)   │
│                       │ retrieved via vector semantic search.                  │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ 6. Calibrated Forecast│ 90-day trajectory with P10/P50/P90 uncertainty corridor│
├───────────────────────┼────────────────────────────────────────────────────────┤
│ 7. Decision Briefing  │ Multi-tiered briefing: Executive Summary, Operational  │
│                       │ Root Cause, and Human Decision Recommendation.         │
└───────────────────────┴────────────────────────────────────────────────────────┘
```

---

## 4. Brand Application Checklist

Before publishing any visual asset, document, or interface component, verify:

- [ ] Does the asset use the approved **Nexus Void (`#060911`)** or **Canvas Light (`#F8FAFC`)** ground?
- [ ] Is the primary symbol placed with at least **`1X` clear space** on all sides?
- [ ] Are all financial and quantitative figures formatted in **JetBrains Mono** with tabular numerals?
- [ ] Are status colors paired with textual labels or geometric icons (WCAG compliance)?
- [ ] Does the copy strictly avoid prohibited buzzwords (*"Magic AI"*, *"Autonomous Brain"*, *"100% Guaranteed"*)?
- [ ] Is the official tagline presented verbatim: `"Where Business Data Becomes Intelligence."`?
