# Agent Security & Isolation Architecture

## Core Security Posture

In conventional LLM-based systems, security vulnerabilities often arise from granting language models direct SQL generation privileges (SQL injection risks) or dynamic code evaluation environments (remote code execution risks).

NEXUS enforces a **zero-trust boundary** between the language model and the execution engine.

---

## Security Invariants

### 1. No Arbitrary SQL Execution
- The LLM never writes raw SQL queries.
- SQL query structures are pre-compiled and managed entirely within the Phase 3 `AnalyticsService` layer using SQLAlchemy parameterized statements.
- Request query strings and filter parameters are never concatenated into raw SQL strings.

### 2. No Code Execution Environment
- The agent does not expose Python `eval()`, `exec()`, or shell execution tools.
- Complex statistics (Welch's t-test, Pearson correlation, quantiles) are executed by audited Python modules (`scipy.stats`, `numpy`, `pandas`) within fixed analytical functions.

### 3. Registry Whitelist Enforcement
- All tool execution must route through `ToolRegistry.execute()`.
- If an agent or malicious prompt attempts to invoke an unregistered tool name (e.g. `execute_bash`, `run_sql`), the registry immediately intercepts the call and returns an explicit `Security violation` result.

### 4. Strict Pydantic Parameter Validation
- Every registered tool enforces a dedicated Pydantic input schema.
- Data types, string patterns, and numeric ranges are validated prior to execution.
- Malformed inputs, injection strings, or unauthorized fields fail at the validation layer.

### 5. Credential & Secret Isolation
- Database credentials, API keys, and server secrets are never injected into system prompts, agent state, or tool parameters.
- Observability logs and execution metadata omit all API keys and credential strings.
