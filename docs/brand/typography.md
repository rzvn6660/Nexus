# NEXUS Typography System

**Document Version**: 1.0  
**Status**: Official Brand Specification  
**Classification**: Typographic Hierarchy & Data Display Standards  

---

## 1. Typographic Philosophy: Scientific Clarity

NEXUS interfaces deal with mission-critical corporate financial metrics, multi-dimensional variance decompositions, and statistical confidence intervals. The typography must therefore deliver **uncompromising legibility, zero ambiguity, and disciplined technical hierarchy**.

We employ a dual-typeface system:
1. **Primary Interface Typeface**: `Inter` — engineered specifically for high-density computer screens, offering exceptional legibility at small sizes and crisp vertical metrics.
2. **Monospace & Numerical Typeface**: `JetBrains Mono` — utilized for all financial metrics, mathematical formulas, SQL queries, evidence packets, and tabular data tables.

```
TYPOGRAPHIC PAIRING
┌─────────────────────────────────┬─────────────────────────────────┐
│ Primary UI / Narrative          │ Numerical / Code / Evidence     │
│ Inter                           │ JetBrains Mono                  │
├─────────────────────────────────┼─────────────────────────────────┤
│ The intelligence pipeline has   │ REVENUE: $4,821,950.00          │
│ isolated a 14.2% margin         │ VARIANCE: -$182,400 (-3.64%)    │
│ contraction in EMEA enterprise. │ P-VALUE:  0.0018 [CONFIRMED]    │
└─────────────────────────────────┴─────────────────────────────────┘
```

---

## 2. Font Stack Specifications

### CSS Font Families:
```css
/* UI, Headings, and General Copy */
--font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;

/* Data Values, Financial Numbers, Code, and Provenance */
--font-mono: 'JetBrains Mono', 'Fira Code', 'SF Mono', Consolas, 'Liberation Mono', Menlo, monospace;
```

---

## 3. Typographic Scale & Hierarchy

```
TYPE SCALE SPECIFICATIONS
┌───────────────┬────────────┬─────────────┬─────────────┬──────────────┬───────────────────────────────────────────┐
│ Level         │ Font Size  │ Line Height │ Weight      │ Letter-Space │ Application                               │
├───────────────┼────────────┼─────────────┼─────────────┼──────────────┼───────────────────────────────────────────┤
│ Display Hero  │ 40px (2.5) │ 48px (1.2)  │ 800 (Extra) │ -0.03em      │ Website hero, slide title, README cover   │
│ Heading 1     │ 28px (1.75)│ 36px (1.28) │ 700 (Bold)  │ -0.02em      │ Main page titles, view headers            │
│ Heading 2     │ 20px (1.25)│ 28px (1.4)  │ 600 (Semi)  │ -0.01em      │ Section headers, card block titles        │
│ Heading 3     │ 16px (1.0) │ 24px (1.5)  │ 600 (Semi)  │ 0.00em       │ Sub-card titles, modal section headers    │
│ Heading 4     │ 14px (0.87)│ 20px (1.42) │ 600 (Semi)  │ +0.01em      │ Metric card labels, table column headers  │
├───────────────┼────────────┼─────────────┼─────────────┼──────────────┼───────────────────────────────────────────┤
│ Body Large    │ 16px (1.0) │ 24px (1.5)  │ 400 (Reg)   │ 0.00em       │ Lead narrative paragraphs, briefing intro │
│ Body Default  │ 14px (0.87)│ 22px (1.57) │ 400 (Reg)   │ 0.00em       │ Standard body copy, investigation explanations│
│ Body Small    │ 12px (0.75)│ 18px (1.5)  │ 400 (Reg)   │ +0.01em      │ Secondary details, parameter descriptions │
├───────────────┼────────────┼─────────────┼─────────────┼──────────────┼───────────────────────────────────────────┤
│ Caption/Meta  │ 11px (0.68)│ 16px (1.45) │ 500 (Med)   │ +0.02em      │ Timestamp footnotes, source table tags    │
│ Eyebrow Tag   │ 11px (0.68)│ 16px (1.45) │ 700 (Bold)  │ +0.08em      │ Uppercase category pills, status badges   │
├───────────────┼────────────┼─────────────┼─────────────┼──────────────┼───────────────────────────────────────────┤
│ Metric Big    │ 32px (2.0) │ 36px (1.12) │ 700 (Bold)  │ -0.02em      │ Primary KPI numbers (JetBrains Mono)      │
│ Metric Regular│ 18px (1.12)│ 24px (1.33) │ 600 (Semi)  │ 0.00em       │ Card secondary metrics, change totals     │
│ Code/SQL      │ 12px (0.75)│ 18px (1.5)  │ 400 (Reg)   │ 0.00em       │ SQL query inspection, raw JSON packets    │
└───────────────┴────────────┴─────────────┴─────────────┴──────────────┴───────────────────────────────────────────┘
```

---

## 4. Numerical & Tabular Data Formatting Rules

When displaying quantitative business intelligence, precision and spatial alignment are paramount:

1. **Tabular Figures (`tnum`)**:
   - Always enforce monospaced figure widths in financial tables and comparative cards using:
     ```css
     font-variant-numeric: tabular-nums;
     ```
   - Prevents jitter and misaligned decimal columns across rows.

2. **Currency & Unit Alignment**:
   - Currency symbols (`$`, `€`, `£`) immediately precede the first digit without space: `$1,250,000`.
   - Percentage signs (`%`) immediately follow the final digit without space: `14.2%`.
   - Positive/Negative variance signs: `+$45,200 (+3.2%)` in Emerald; `-$112,000 (-5.8%)` in Rose.

3. **Decimal Consistency**:
   - High-level KPIs: Round to 1 decimal place (`$4.2M`, `+12.4%`).
   - Detailed variance analysis: Standardize to exactly 2 decimal places (`$4,218,940.25`, `+12.42%`).
   - P-values / Statistical significance: Standardize to 3 or 4 decimal places (`p = 0.0018`).

---

## 5. Typographic Contrast & Readability Rules

- **Header Case**: Sentence case is strictly preferred for headings (`"Diagnostic investigation results"` rather than Title Case `"Diagnostic Investigation Results"`), except for official product section titles and the uppercase brand wordmark.
- **Eyebrow Tags**: Always set in uppercase with increased letter spacing (`+0.08em`): e.g., `EVIDENCE PROVENANCE`, `INVESTIGATION PIPELINE`, `CONFIDENCE INTERVAL`.
- **Line Length**: Paragraph body text must never exceed 75 characters per line (`max-w-2xl` or `680px`) to prevent visual fatigue.
