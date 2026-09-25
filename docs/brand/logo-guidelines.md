# NEXUS Logo Guidelines

**Document Version**: 1.0  
**Status**: Official Brand Specification  
**Classification**: Visual Identity & Brand Standards  

---

## 1. Logo Concept Exploration

Before arriving at the official NEXUS identity, four distinct geometric and conceptual directions were developed and evaluated against the platform's core mission: **Connection → Intelligence → Decision**.

```
CONCEPT EXPLORATION MATRIX
┌─────────────┬──────────────────────────┬─────────────────────────┬─────────────────────────┬─────────────────────────┐
│ Metric      │ Concept A:               │ Concept B:              │ Concept C:              │ Concept D: Geometric    │
│             │ Convergence Delta        │ Vector Intersection     │ Modular Hex Nexus       │ Nexus Node [SELECTED]   │
├─────────────┼──────────────────────────┼─────────────────────────┼─────────────────────────┼─────────────────────────┤
│ Visual Idea │ Converging vectors       │ Two offset orthogonals  │ Hexagonal network ring  │ Dual vertical data rails│
│             │ meeting at a point       │ forming an abstract N   │ with an illuminated core│ bridged to diamond node │
│ Symbolism   │ Disparate streams        │ Structural connection   │ Data warehousing        │ Data + Context meeting  │
│             │ focusing on insight      │ across silos            │ semantic architecture   │ at human decision core  │
│ Scalability │ Moderate (point blurs    │ High (bold strokes)     │ Low at <24px (interior  │ Exceptional: crisp down │
│             │ at 16px)                 │                         │ lines merge)            │ to 16px pixel-grid      │
│ Favicon     │ Acceptable               │ Strong                  │ Weak                    │ Flawless (high contrast)│
│ Monochrome  │ Excellent                │ Good                    │ Complex fills           │ Perfect balance         │
└─────────────┴──────────────────────────┴─────────────────────────┴─────────────────────────┴─────────────────────────┘
```

### Concept A: The Convergence Delta
- **Visual Idea**: Three discrete ray vectors originating from different coordinates, converging into a forward-pointing precision chevron.
- **Symbolism**: Represents raw data, context, and analytics streaming together toward forward momentum.
- **Evaluation**: Strong conceptual story, but at 16px favicon resolution, the thin convergence point becomes indistinct on low-DPI displays.

### Concept B: Vector Intersection
- **Visual Idea**: Two bold, offset vertical columns joined by an angled dynamic transversal, forming a sharp abstract letterform.
- **Symbolism**: Represents the bridge between the enterprise data warehouse and the executive boardroom.
- **Evaluation**: Highly legible and scalable, but felt slightly generic without an explicit representation of the central decision focal point.

### Concept C: Modular Hex Nexus
- **Visual Idea**: An isometric hexagonal lattice with a central highlighted hub node and interconnecting spokes.
- **Symbolism**: Represents graph databases, semantic ontologies, and multi-agent coordination.
- **Evaluation**: Communicated technical depth, but excessive internal complexity caused stroke collision and loss of definition at 24px and below.

### Concept D: The Geometric Nexus Node [FINAL SELECTED DIRECTION]
- **Visual Idea**: Two parallel vertical data rails representing empirical enterprise inputs (Data & Context), seamlessly bridged by an acute transversal running into an illuminated central diamond decision node.
- **Symbolism**: Encapsulates the complete NEXUS pipeline: raw inputs are structured, bridged, and concentrated into a focal decision core. It subtly evokes an architectural 'N' while remaining an autonomous, recognizable geometric icon.
- **Scalability**: Perfect geometric balance across all scales, from 16px favicon to 1200px billboard displays.
- **Favicon Suitability**: Unmatched clarity; the diamond core and vertical pillars preserve negative space even on 16×16 raster grids.
- **Monochrome Suitability**: Strong outline and silhouette integrity without relying on color or glow filters.

---

## 2. Primary Symbol Construction

The NEXUS symbol is built on a precise Cartesian grid (viewBox: `0 0 64 64`).

```
         ┌───┐                 ┌───┐
         │   │                 │   │
         │   │      / \        │   │
         │   │     /   \       │   │
         │   │    /  ◆  \      │   │
         │   │   /       \     │   │
         │   └──/         \────┤   │
         │   │ \           /   │   │
         │   │  \         /    │   │
         │   │   \       /     │   │
         └───┘    \     /      └───┘
                   \   /
                    \ /
```

### Geometric Specifications:
1. **Left Input Rail (Data)**:
   - Coordinates: `x="8"`, `y="8"`, `width="9"`, `height="48"`, `rx="4"`.
   - Gradient: Flowing from Nexus Cyan (`#00F2FE`) to Nexus Deep Cyan (`#0284C7`).
2. **Right Input Rail (Context)**:
   - Coordinates: `x="47"`, `y="8"`, `width="9"`, `height="48"`, `rx="4"`.
   - Gradient: Flowing from Nexus Blue (`#38BDF8`) to Nexus Electric Indigo (`#6366F1`).
3. **Traversing Convergence Bridge**:
   - Diagonal corridor linking the upper-left data rail through the center down to the lower-right context rail.
   - Geometry: Polygon connecting points `(17, 10)`, `(47, 54)`, `(41, 54)`, and `(17, 18)`.
4. **Central Decision Focal Core (Diamond)**:
   - Rotated square centered at `(32, 32)` with diameter of 16px.
   - Points: `(32, 22) -> (42, 32) -> (32, 42) -> (22, 32)`.
   - Fill: Luminous white (`#FFFFFF`) with subtle outer drop glow (`#00F2FE`, 8px blur, opacity 0.8) on dark canvases.

---

## 3. Wordmark Construction

The wordmark **NEXUS** is set in an ultra-clean, geometric sans-serif aesthetic with generous tracked spacing, embodying modern precision engineering.

- **Typeface Base**: Customized geometric sans (Inter / Space Grotesk / Montserrat Geometric profile).
- **Case**: All Caps (`N E X U S`).
- **Letter Spacing / Tracking**: `+0.25em` to `+0.35em` for display lockups, ensuring air and high-end technical poise.
- **Weight**: Bold (`font-weight: 700` or `800`) to counterbalance the stroke weight of the symbol.
- **Coloration**:
  - Dark Mode: Pure White (`#FFFFFF`) with subtle gradient termination in Slate 200 (`#E2E8F0`).
  - Light Mode: Deep Void Slate (`#0B1120`) for uncompromising typographic authority.

---

## 4. The Logo Lockup System

The NEXUS brand system includes ten official production lockup assets located in the `brand/` directory:

```
brand/
├── logo/
│   ├── primary/
│   │   ├── nexus-primary-logo-dark.svg      # Master horizontal lockup (Dark background)
│   │   ├── nexus-primary-logo-light.svg     # Master horizontal lockup (Light background)
│   │   ├── nexus-primary-logo-compact.svg   # Stacked / square 320x320 lockup
│   │   ├── nexus-wordmark-dark.svg          # Wordmark-only (Dark canvas)
│   │   └── nexus-wordmark-light.svg         # Wordmark-only (Light canvas)
│   ├── symbol/
│   │   ├── nexus-symbol.svg                 # Standalone symbol (Dark background)
│   │   ├── nexus-symbol-light.svg           # Standalone symbol (Light background)
│   │   ├── nexus-symbol-monochrome-black.svg# Pure black vector symbol
│   │   └── nexus-symbol-monochrome-white.svg# Pure white vector symbol
│   ├── monochrome/
│   │   ├── nexus-logo-monochrome-black.svg  # Complete lockup in pure #000000
│   │   └── nexus-logo-monochrome-white.svg  # Complete lockup in pure #FFFFFF
│   ├── dark/
│   │   └── nexus-logo-dark.svg              # Standalone dark mode asset
│   └── light/
│       └── nexus-logo-light.svg             # Standalone light mode asset
├── favicon/
│   └── favicon.svg                          # 32x32 pixel-snapped browser favicon
├── github/
│   ├── nexus-github-avatar.svg              # 400x400 1:1 repository avatar
│   └── nexus-readme-banner.svg              # 1280x480 high-res hero banner
└── social/
    └── nexus-social-card.svg                # 1200x630 OpenGraph / LinkedIn social preview
```

---

## 5. Clear Space & Proportions

To maintain visual integrity and brand prominence, the logo must always be surrounded by an exclusion zone free of text, borders, illustrations, or other graphical marks.

```
       ┌────────────────────────────────────────────────────────┐
       │                       ▲                                │
       │                       │ X                              │
       │                       ▼                                │
       │     ┌───────────┐           ┌───────────────────┐      │
       │◄─X─►│  SYMBOL   │◄── 1.5X ─►│    N E X U S      │◄─X─► │
       │     └───────────┘           └───────────────────┘      │
       │                       ▲                                │
       │                       │ X                              │
       │                       ▼                                │
       └────────────────────────────────────────────────────────┘
```

- **Clear Space Unit (X)**: Defined as the vertical height of the central diamond node in the symbol (equal to 25% of the total symbol height).
- **Minimum Clear Space**: `1X` on all four sides of any lockup.
- **Symbol-to-Wordmark Gap**: `1.5X`.

---

## 6. Sizing Rules & Micro-Scale Rendering

The NEXUS symbol has been engineered and tested across standard digital breakpoints:

| Target Size | Use Case | Rendering Behavior |
|---|---|---|
| **16px** | Browser tab favicon (low-DPI) | Use `brand/favicon/favicon.svg`. Drop-shadows and subtle blurs are removed to ensure zero subpixel antialiasing smearing. |
| **24px** | Application top navigation bar / breadcrumbs | Standard vector symbol; rails and diamond remain crisp. |
| **32px** | Standard browser favicon / taskbar icon | High definition; full gradient transitions visible. |
| **48px** | Product sidebar collapsed header | Full color gradient with subtle outer glow. |
| **64px** | Primary horizontal logo in app headers | Full lockup with wordmark and subtitle. |
| **128px+** | GitHub profile avatar, website hero, slide deck covers | Full visual fidelity including radial lens glow. |

---

## 7. Incorrect Usage (Don'ts)

To preserve the credibility and authority of the NEXUS brand, adhere strictly to the following prohibitions:

1. **DO NOT stretch, condense, or distort** the symbol or wordmark disproportionately.
2. **DO NOT rotate** the symbol at arbitrary angles. The vertical rails must remain strictly perpendicular.
3. **DO NOT apply unapproved color gradients** (e.g., rainbow, fluorescent green, purple-magenta synthwave).
4. **DO NOT replace the wordmark font** with decorative, serif, handwritten, or sci-fi display fonts.
5. **DO NOT enclose the logo in heavy drop-shadow boxes** or cheesy 3D bevels.
6. **DO NOT place the full-color dark logo on low-contrast backgrounds**; use the monochrome or light-mode lockups accordingly.
7. **DO NOT crowd the mark** with competing typography or overlapping UI badges closer than the `1X` clear-space boundary.
