# NEXUS Decision Gateway Architecture (Phase 12A)

> **Phase Declaration**:  
> Phase 12A introduces the Decision Gateway abstraction and establishes the current LLM-backed baseline. Jev integration is intentionally deferred to Phase 12B.

---

## 1. Why the Decision Gateway Exists

NEXUS workflows perform two fundamentally distinct kinds of AI operations:
1. **Generative Synthesis & Explanations**: Creating clear, professional, multi-paragraph executive analytical dossiers. (Requires general-purpose autoregressive LLMs like GPT-4o or Claude 3.5 Sonnet).
2. **Structured Decisions**: High-frequency, discrete, schema-bounded operational determinations:
   - Intent classification (routing a question to 1 of 10 analytical domains).
   - Tool selection (choosing from 16 allowlisted deterministic tools).
   - RAG chunk reranking (scoring relevance of retrieved policy excerpts).
   - Evidence sufficiency evaluation (determining whether collected SQL data answers the inquiry).
   - Diagnostic investigation routing (selecting an investigation archetype).
   - Risk gating & HITL review thresholds (scoring financial impact and decision severity).

Historically, general-purpose LLMs were invoked for both kinds of tasks. For discrete decision tasks, autoregressive token generation introduces:
- High latency (400ms – 1,200ms per classification turn).
- Unnecessary token compute costs.
- Risk of JSON syntax degradation or hallucinated keys.
- Uncalibrated confidence scores.

The **Decision Gateway** provides a unified, provider-independent architectural abstraction separating *decision execution* from specific AI vendor implementations.

---

## 2. Gateway Abstraction & Architecture

```
                                  Caller Request
                 (Agent Node, Investigation Engine, RAG Pipeline)
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │    DecisionRequest    │
                            │  - task               │
                            │  - input_text         │
                            │  - candidate_options  │
                            │  - context            │
                            │  - constraints        │
                            └───────────┬───────────┘
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │    DecisionGateway    │
                            └───────────┬───────────┘
                                        │
                        Provider Resolution via Config
                    (DECISION_PROVIDER="structured_llm")
                                        │
         ┌──────────────────────────────┴──────────────────────────────┐
         ▼                                                             ▼
┌─────────────────────────────────┐                   ┌─────────────────────────────────┐
│  StructuredLLMDecisionProvider  │                   │      MockDecisionProvider       │
│  - Production LLM Provider      │                   │  - Deterministic Test Provider  │
│  - Strict JSON Output           │                   │  - Zero Network Calls           │
│  - Normalized Errors            │                   │  - Configurable Overrides       │
│  - Real Telemetry & Cost        │                   │  - Timeout/Error Simulation     │
└────────────────┬────────────────┘                   └────────────────┬────────────────┘
                 │                                                     │
                 └──────────────────────────────┬──────────────────────┘
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │    DecisionResult     │
                                    │  - task               │
                                    │  - status             │
                                    │  - decision           │
                                    │  - structured_output  │
                                    │  - rationale          │
                                    │  - confidence         │
                                    │  - telemetry          │
                                    └───────────────────────┘
```

---

## 3. Provider Implementations

### A. Structured LLM Provider (`structured_llm`)
- **Role**: Current production baseline provider adapting OpenAI-compatible language models.
- **Execution**: Sends typed decision schemas with `response_format={"type": "json_object"}` at temperature `0.0`.
- **Telemetry**: Measures millisecond execution latency and tracks exact prompt, completion, and total tokens used. Computes dollar cost estimates using verified model rate sheets.
- **Honest Confidence**: Does not invent fabricated confidence probabilities. If the underlying model does not output a calibrated probability, `confidence` is reported strictly as `None`.

### B. Mock Decision Provider (`mock`)
- **Role**: Test and offline development provider.
- **Determinism**: 100% offline, zero network or external API dependencies.
- **Simulation Capabilities**: Supports `.set_response()`, `.set_error()`, and `.set_timeout()` to verify system robustness under degraded infrastructure conditions.
- **Environment Isolation**: Automatically selected when `APP_ENV == "test"`.

---

## 4. Critical Production Safety Invariants

### 1. No Silent Mock Fallback in Production
In live production environments, a failure in the LLM provider (network timeout, rate limit, authentication error) must **NEVER** silently switch to a mock response to pretend execution succeeded.
- Live failures raise a normalized `DecisionProviderUnavailableError` or `DecisionTimeoutError`.
- Or emit an explicitly flagged `DecisionResult(status=DecisionStatus.FAILED, error_message=...)`.
- Mock provider must be explicitly selected; it can never masquerade as live intelligence.

### 2. Candidate Option Enforcement
If a request specifies `candidate_options` (e.g. `["metric_lookup", "comparison", "trend"]`), the gateway verifies that the provider's returned `decision` belongs to the candidate list. If not, the result status is downgraded to `DEGRADED` and flagged with an audit warning.

### 3. Absolute Mathematical Isolation
The Decision Gateway handles routing, ranking, and classification only. It is strictly prohibited from performing mathematical aggregations, financial calculations, or SQL execution. All numbers continue to be generated exclusively by the deterministic `AnalyticsService`.

---

## 5. Telemetry & Cost Tracking

Every `DecisionResult` carries a strongly-typed `DecisionTelemetry` record:
```json
{
  "provider": "structured_llm",
  "model": "gpt-4o",
  "latency_ms": 54.2,
  "tokens_used": 145,
  "prompt_tokens": 120,
  "completion_tokens": 25,
  "estimated_cost_usd": 0.00055,
  "timestamp": "2026-09-26T18:20:00Z"
}
```

This telemetry infrastructure provides the exact baseline required for empirical comparison against Jev in Phase 12B.

---

## 6. Future Jev Integration Point (Phase 12B)

In Phase 12B, the Jev provider will be integrated as:
```python
# backend/app/decisions/providers/jev.py (PHASE 12B)
class JevDecisionProvider(BaseDecisionProvider):
    @property
    def provider_name(self) -> str:
        return "jev"
    
    def execute_decision(self, request: DecisionRequest) -> DecisionResult:
        # Executes structured decision via Jev runtime
        ...
```

Selecting Jev will require only setting:
```bash
DECISION_PROVIDER=jev
```
with zero changes required in agent nodes, investigation pipelines, or RAG components.

---

## 7. What is Intentionally NOT Implemented in Phase 12A

1. **No Jev Dependencies or Packages**: No Jev libraries are installed or referenced.
2. **No OKF Knowledge Bundles**: OKF implementation is reserved for Phase 14.
3. **No Multi-Tenancy / SaaS Billing**: The architecture remains single-tenant.
4. **No Full Graph Rewriting**: LangGraph workflow remains intact; only intent routing is initially adapted through the gateway.
5. **No Frontend Redesign**: UI contracts and layouts are completely preserved.
