# NEXUS Visual Language

**Document Version**: 1.0  
**Status**: Official Brand Specification  
**Classification**: Visual Design System & Aesthetics  

---

## 1. Visual Philosophy: Disciplined Architecture

The visual language of NEXUS is anchored in **geometric structure, connected evidence, and controlled depth**. 

Every visual component in NEXUS mirrors the rigorous architecture of the underlying engine:
- Data flows along visible, structured pathways.
- Analytical claims are anchored to tangible evidence nodes.
- Depth is subtle and physical—surfaces float with crisp 1px borders rather than blurry, exaggerated drop shadows.

```
VISUAL PILLARS
┌───────────────────────┬───────────────────────┬───────────────────────┐
│ Structured Geometry   │ Connected Evidence    │ Controlled Depth      │
├───────────────────────┼───────────────────────┼───────────────────────┤
│ Pure rectangular cards│ Directed vectors and  │ High-clarity 1px      │
│ with restrained radii │ step nodes connecting │ borders over optical  │
│ (8px to 12px)         │ input to conclusion   │ void canvas           │
└───────────────────────┴───────────────────────┴───────────────────────┘
```

---

## 2. Core Visual Motifs

To express the concept of *"Where Business Data Becomes Intelligence,"* NEXUS employs seven restrained visual motifs:

### 1. The Decision Junction (Focal Core)
- **Form**: The 45-degree rotated diamond node.
- **Meaning**: The focal point where disparate quantitative streams intersect to require human executive judgment.
- **Usage**: Primary brand symbol, stage markers in the LangGraph visual pipeline, and approved decision gates.

### 2. Dual-Stream Convergence
- **Form**: Two parallel orthogonal rails converging via an angled traversal.
- **Meaning**: Empirical warehouse data (left) uniting with corporate business context (right).
- **Usage**: Architecture diagrams, section dividers, and hero graphic backgrounds.

### 3. The Evidence Badge
- **Form**: Monospaced pill container with a subtle cyan/indigo radial glow, 1px border, and leading geometric status pip.
- **Meaning**: Signifies that the associated metric is deterministically verified with audit provenance.
- **Usage**: `[SQL-VERIFIED]`, `[RAG-GROUNDED: POLICY §4.2]`, `[P-VALUE: 0.0018]`.

### 4. Structural Dot & Line Grids
- **Form**: Ultra-subtle dot matrices (spacing: 24px, opacity: 0.04 to 0.08) or faint orthogonal gridlines.
- **Meaning**: Represents the structured dimensional model and mathematical plane of analysis.
- **Usage**: Background canvases in presentation slides, website hero backdrops, and diagram canvases.

### 5. Stepped Pipeline Nodes
- **Form**: Horizontal sequence of rounded rectangle pills connected by directional chevron connectors (`──►`).
- **Meaning**: Reflects the 11-step intelligence pipeline (`Data -> Understand -> Check -> Analyze...`).
- **Usage**: Workflow execution monitors, progress indicators, and slide section headers.

### 6. Calibrated Uncertainty Bands
- **Form**: Crisp central trajectory line bounded by a translucent, shaded corridor (opacity: 0.15).
- **Meaning**: Honest representation of statistical confidence intervals (P10–P90) rather than deterministic illusion.
- **Usage**: Predictive intelligence charts, forecast visualizers.

### 7. Dimensional Decomposition Bars
- **Form**: Waterfall-style step bars in emerald (favorable) and rose (unfavorable), terminating in net variance.
- **Meaning**: Explaining the exact causal drivers (Price vs. Volume vs. Mix).
- **Usage**: Investigation view, variance audit cards.

---

## 3. Surface Architecture & Elevation

NEXUS achieves visual depth through **tonal elevation and border contrast** rather than aggressive shadows.

```
ELEVATION STACK
┌────────────────────────────────────────────────────────┐
│ Level 3: Modals / Floating Tooltips (z-50)             │
│ Bg: #1E293B (rgba 0.95), Border: #38BDF8 (Cyan 1px)    │
│ Box-Shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5)        │
├────────────────────────────────────────────────────────┤
│ Level 2: Interactive Cards / Dropdowns / Pills (z-10)  │
│ Bg: #0F172A (Surface Slate), Border: #334155 (1px)     │
│ Box-Shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3)         │
├────────────────────────────────────────────────────────┤
│ Level 1: Static Structural Panels & Sidebars (z-0)     │
│ Bg: #090D16, Border: #1E293B (1px divider)             │
├────────────────────────────────────────────────────────┤
│ Level 0: Master Application Canvas (Void)              │
│ Bg: #060911                                            │
└────────────────────────────────────────────────────────┘
```

### Corner Radius Standards:
- **Outer Page Containers**: `rounded-2xl` (16px)
- **Interactive KPI Cards / Panels**: `rounded-xl` (12px)
- **Inner Sub-blocks / Tables / Form Inputs**: `rounded-lg` (8px)
- **Status Tags / Evidence Badges / Pills**: `rounded-full` (9999px)

---

## 4. Iconography Standards

Iconography in NEXUS reinforces technical clarity and speed of recognition.

### Principles:
1. **Geometric & Linear**: Icons must use consistent 1.5px or 2px stroke weights.
2. **Standard Library**: Built on **Lucide Icons** to maintain seamless parity with Phase 8 frontend components.
3. **No Decorative Clutter**: Icons are never used as purely ornamental filler. Every icon corresponds to an operational state or tool category.
4. **Color Synchronization**:
   - Navigation & Inactive: `#94A3B8` (Text Secondary)
   - Active Section: `#38BDF8` (Nexus Sky)
   - Success / Confirmation: `#10B981` (Emerald)
   - Anomaly Alert: `#F43F5E` (Rose)

---

## 5. Visual Language Dos & Don'ts

| DO | DON'T |
|---|---|
| Use 1px sharp borders with `#1E293B` or `#334155` | Use heavy, blurry black drop shadows |
| Highlight key focal points with electric cyan `#00F2FE` | Scatter random neon rainbow colors across the interface |
| Anchor metrics with provenance badges | Present isolated numbers without data source or time window |
| Use monospaced font for all numerical values | Mix variable-width fonts in financial tables |
| Keep background textures under 8% opacity | Use busy, high-contrast wallpaper patterns |
| Represent forecasting with honest uncertainty corridors | Show forecasts as single, guaranteed flat lines |
