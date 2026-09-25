# NEXUS Design System Specification

**Document Version**: 1.0  
**Status**: Official Interface Architecture Specification  
**Classification**: Component Primitives, Chromatic Tokens, and Interaction Models  

---

## 1. Core Principles: Quiet Intelligence

The NEXUS Design System exists to support rigorous, evidence-grounded decision making. It deliberately avoids the visual tropes of speculative generative AI (excessive glowing neon, dancing particle fields, floating 3D spheres) in favor of **calm, optical precision**.

1. **Substance over Spectacle**: Every visual element must convey real analytical information.
2. **Deterministic Clarity**: Users must instantly distinguish between an empirical fact, a tested hypothesis, a predictive forecast, and a human recommendation.
3. **Progressive Disclosure**: High-level executive briefings come first; cryptographic SQL lineage, row-level filters, and backtest errors are accessible in one click.
4. **Human Authority**: The machine proposes, explains, and provides evidence; the human operator reviews, modifies, and decides.

---

## 2. Design Tokens

### 2.1 Chromatic Tokens
The palette is derived directly from `docs/brand/color-system.md`:

```css
:root {
  /* Surfaces & Grounds */
  --nexus-void: #060911;          /* Master application ground */
  --nexus-void-sub: #090D16;      /* Sub-canvases, header stripes, card backdrops */
  --nexus-slate: #0F172A;         /* Primary panel & card surface */
  --nexus-elevated: #1E293B;      /* Hover states, active dropdowns, pill tags */
  
  /* Borders & Dividers */
  --nexus-border-subtle: #1E293B; /* Structural borders, gridlines */
  --nexus-border-focus: #334155;  /* Focus rings, active selection boundaries */
  --nexus-border-cyan: rgba(0, 242, 254, 0.25); /* Active intelligence nodes */
  
  /* Brand Luminescence */
  --nexus-cyan: #00F2FE;          /* Active decision core, primary accents */
  --nexus-sky: #38BDF8;           /* Primary interactive elements, links */
  --nexus-sapphire: #0284C7;      /* Primary CTA fill, gradient origin */
  --nexus-indigo: #6366F1;        /* RAG semantic highlights, diagnostic tags */
  
  /* High-Contrast Typography */
  --nexus-text-primary: #F8FAFC;  /* Headings, KPI values, core statements */
  --nexus-text-secondary: #94A3B8;/* Explanations, subheads, descriptions */
  --nexus-text-muted: #64748B;    /* Footnotes, timestamps, line numbers */
  
  /* Directional & Health Semantics */
  --nexus-success: #10B981;       /* Positive variance, healthy data check */
  --nexus-warning: #F59E0B;       /* Margin compression, data warnings */
  --nexus-danger: #F43F5E;        /* Anomaly alert, revenue decline, error */
}
```

### 2.2 Typography
- **Primary Interface**: `Inter`, system-ui, -apple-system, BlinkMacSystemFont, sans-serif.
- **Code, Data Lineage & Metrics**: `JetBrains Mono`, monospace.
- **Scale**:
  - `Hero Statement`: 28px – 32px / 1.2 / Weight 700
  - `Section Header`: 20px – 24px / 1.3 / Weight 600
  - `Card Header / Metric Title`: 14px – 16px / 1.4 / Weight 600
  - `Body / Findings`: 13px – 14px / 1.5 / Weight 400–500
  - `Telemetry / Meta`: 11px – 12px / 1.4 / Weight 500 (`font-mono`)

---

## 3. Component Primitive Catalog

### 3.1 `NexusShell`
The global intelligence workspace container. Features a top brand bar, collapsible navigation rail, responsive viewport canvas, and persistent slide-out context drawer.

### 3.2 `NexusSymbol` & `NexusLogo`
Pure SVG rendering of the official NEXUS convergence mark (`brand/logo/symbol/nexus-symbol.svg`). Preserves radial glow, dual rails, and the central decision diamond at 16px, 24px, 32px, and 48px sizes without pixel distortion.

### 3.3 `IntelligenceHeader`
Standardized page header displaying the domain eyebrow, bold title, descriptive subtitle, and integrated action triggers (Search, Ask NEXUS, System Status).

### 3.4 `IntelligenceStage`
Subtle step-by-step indicator for agentic reasoning and diagnostic execution:
$$\text{UNDERSTAND} \longrightarrow \text{INVESTIGATE} \longrightarrow \text{VALIDATE} \longrightarrow \text{PREDICT} \longrightarrow \text{DECIDE}$$
Communicates execution stage and human-readable tool status without leaking raw internal reasoning.

### 3.5 `FindingBlock`
Structured intelligence finding container separating:
- **Observation / Statement**
- **Quantified Drivers**
- **Evidence Verification Action**
- **Strategic Next Steps**

### 3.6 `SignalRow`
Compact, high-density briefing row for executive telemetry:
- **WHAT**: Quantitative shift
- **WHY IT MATTERS**: Commercial context
- **INSPECT**: Direct investigation trigger

### 3.7 `InvestigationPath`
Visual diagnostic tree component rendering root metrics, decomposed drivers (Category, Product, Mix, Cohort), and verified vs rejected hypotheses.

### 3.8 `ForecastBand`
Prospective predictive chart presentation uniting observed history, point forecast, and shaded statistical prediction intervals, accompanied by backtested MAE/sMAPE scorecards and explicit modeling assumptions.

### 3.9 `DecisionCard`
Interactive human review surface for proposed recommendations:
- Displays proposal summary, estimated impact, and evidence confidence
- Provides action controls: `APPROVE`, `REJECT`, `MODIFY`
- Captures reviewer notes for immutable audit persistence

### 3.10 `EvidenceDrawer` / `EvidencePanel`
Dual-view provenance drawer:
- **Executive View**: Business logic, plain-English justification, policy citations
- **Analyst Audit View**: Full database tables, columns, SQL predicates, latency, and SHA-256 cryptographic hash

---

## 4. Interaction & Motion Standards

1. **Motion Duration**: Micro-interactions must complete in 150ms – 200ms; page transitions in 200ms – 300ms.
2. **Motion Purpose**: Motion indicates information progression, data loading, or panel state; never purely decorative bouncing or continuous drifting.
3. **Accessibility**: All animations honor `@media (prefers-reduced-motion: reduce)` by falling back to immediate opacity swaps.
