# Forecasting Limitations

## Overview
Transparency requires clear, explicit communication of analytical limitations.

---

## 1. Structural Limitations
- **Exogenous Shocks**: Time-series models extrapolate from past patterns and cannot anticipate sudden unobserved structural shifts (e.g. regulatory disruptions, macroeconomic shocks, new competitor entries).
- **History Requirements**: Series with fewer than the minimum observation count (e.g. newly introduced products) cannot support reliable statistical models.
- **Intermittent Demand**: For products with sporadic, bursty sales followed by extensive periods of zero demand, standard continuous models have wider prediction intervals.

---

## 2. Model Scope Limitations
- **Univariate Forecasting**: Phase 7 models are univariate (predicting target $y$ from historical $y$). Cross-series hierarchy reconciliation and complex exogenous regressors are reserved for future phases.
- **Static Baseline**: Parameter optimization does not dynamically account for price elasticity unless modeled as an explicit scenario in future phases.

---

## 3. Prescriptive Boundary
- Predictions represent probabilistic future trajectories. They do not constitute operational instructions, purchasing directives, or pricing mandates.
