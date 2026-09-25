# Predictive Security & Safeguards

## Overview
Phase 7 preserves and enforces all security controls established across previous phases.

---

## 1. Zero Arbitrary Execution
- **No Arbitrary Code**: The system executes pre-compiled mathematical routines. No Python `eval()`, `exec()`, or dynamic scripting is executed.
- **No Arbitrary SQL**: All time-series extraction queries utilize parameterized SQLAlchemy ORM models.
- **No Shell or Filesystem Execution**: No subprocesses, system commands, or unvetted filesystem writes are permitted.

---

## 2. Tool Registry Whitelist
Forecasting is exposed through the formal `forecast_metric` tool registered in `ToolRegistry`.
- Tool invocations are strictly schema-validated via Pydantic (`ForecastMetricToolInput`).
- Non-whitelisted tools are rejected immediately.

---

## 3. Horizon Constraints
- Maximum forecast horizon is clamped to `MAX_FORECAST_HORIZON` (default: 12).
- Attempts to request horizons beyond the configured maximum trigger strict 422 HTTP validation errors.

---

## 4. Anti-Prescriptive Safeguards
To prevent overstepping into prescriptive autonomy (Phase 8):
- All generated explanations pass through `CausalitySafeguard.sanitize_diagnostic_text`.
- Imperative phrases like "order 500 units", "raise prices", "reduce staff", or "increase inventory" are automatically neutralized or blocked.
