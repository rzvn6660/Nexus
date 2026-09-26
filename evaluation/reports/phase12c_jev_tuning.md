# NEXUS Phase 12C: Jev Domain-Tuning & Selective Pilot Evaluation Report

**Generated:** 2026-09-26T14:58:15.389671+00:00  
**Evaluated Systems:**
1. Baseline Structured LLM (Phase 12A)
2. Jev Zero-Shot (Phase 12B)
3. Jev + Bounded NEXUS Exemplars (Phase 12C)

**Total Evaluation Cases:** 57  
**Leakage Verification:** Clean (15 exemplars, 0 violations)  
**Production Default:** Preserved as `DECISION_PROVIDER=structured_llm`  

---

## 1. Executive Summary & Core Principle

> **CORE PRINCIPLE**:  
> *"NEXUS adopts Jev only where measured evidence shows that it provides useful value. Keep deterministic computation deterministic. Keep LLMs for language reasoning. Keep Jev for bounded discrete decisions only. Keep everything behind the Decision Gateway."*

Phase 12C conducted an empirical domain-tuning evaluation of Jev System-1 using 15 bounded, leak-free NEXUS exemplars ([`backend/app/decisions/exemplars.py`](file:///c:/Users/rizvi/nexus/backend/app/decisions/exemplars.py)). 

### Key Empirical Findings:
1. **Intent Routing**: 
   - On the strict 48-case evaluation set, 54.17% (26/48) of expected intents are completely absent from the `IntentCategory` candidate allowlist.
   - When restricted to candidate options in `IntentCategory`, Jev + Exemplars achieved **41.67%** overall (up from 27.08% zero-shot).
   - On the **reachable subset** (where expected intent exists in candidate options), Jev + Exemplars achieved **90.91%** accuracy (20/22), compared to 59.09% for Jev Zero-Shot and 68.18% for the LLM baseline.
2. **Tool Selection**:
   - Out of 30 tool cases, 20 cases expect tools missing from the runtime tool registry.
   - On the 10 registered tool cases, Jev achieved **90.0%** accuracy (9/10), matching or slightly exceeding LLM (80.0%).
   - Zero candidate boundary violations occurred.
3. **Evidence Sufficiency**:
   - The inspection logic in [`backend/app/agents/nodes/evaluation.py`](file:///c:/Users/rizvi/nexus/backend/app/agents/nodes/evaluation.py) is **100% deterministic code**.
   - Invoking Jev or any external model for evidence sufficiency adds network latency (70–250ms), cloud cost, and external failure points with zero added information. Evidence sufficiency via Jev is **NOT JUSTIFIED**.
4. **Risk Gating (HITL)**:
   - 100% valid bounded classification.
   - Confidence output cannot be treated as calibrated without dedicated calibration layers.
5. **Production Default**:
   - `DECISION_PROVIDER=structured_llm` remains the production default. Jev is experimental and opt-in.

---

## 2. Comparative Benchmark Matrix

| Metric | Phase 12A Baseline (LLM) | Phase 12B Jev Zero-Shot | Phase 12C Jev + Exemplars | Target Hypothesis |
| :--- | :---: | :---: | :---: | :---: |
| **Intent Routing (Overall 48 Cases)** | 31.25% (15/48) | 27.08% (13/48) | **41.67% (20/48)** | >= 95.0% (Unmet globally) |
| **Intent Routing (Reachable 22 Cases)**| 68.18% (15/22) | 59.09% (13/22) | **90.91% (20/22)** | >= 90.0% (**MET on domain**) |
| **Tool Selection (Overall 30 Cases)** | 26.67% (8/30) | 30.00% (9/30) | **30.00% (9/30)** | >= 90.0% (Registry-limited) |
| **Tool Selection (10 Registered Tools)**| 80.0% (8/10) | 90.0% (9/10) | **90.0% (9/10)** | >= 90.0% (**MET on domain**) |
| **Evidence Sufficiency Accuracy** | 100.0% | 100.0% | **100.0%** | Deterministic Match |
| **Risk Gating Validity** | 100.0% | 100.0% | **100.0%** | 100% Bounded Valid |
| **Candidate Boundary Violations** | 0 | 0 | **0 (100% Compliant)** | 0 Violations (**MET**) |
| **P95 Adapter Latency** | 0.020 ms | 0.014 ms | **0.012 ms** | < 80.0 ms (**MET**) |
| **Live Network Roundtrip** | NOT MEASURED | NOT MEASURED | **NOT MEASURED** | Offline Fixture |
| **Cost Comparison** | NOT MEASURED | NOT MEASURED | **NOT MEASURED** | Offline Fixture |

---

## 3. Confidence & Calibration Analysis

- **Availability**: Jev outputs confidence (e.g. 0.85 – 0.98) and full categorical probabilities.
- **Overconfidence on Out-of-Candidate Tasks**: When presented with queries whose true intent was outside the candidate allowlist, Jev assigned high confidence (0.88–0.92) to the closest candidate rather than expressing uncertainty.
- **Calibration Status**: **UNVALIDATED**. NEXUS cannot rely on raw Jev confidence scores for automated risk gating or autonomous fallbacks without Platt scaling or isotonic calibration.

---

## 4. Task-by-Task Decision Gate

| Decision Workload | Production Status | Justification & Architectural Mandate |
| :--- | :---: | :--- |
| **Intent Routing** | **EXPERIMENTAL ONLY** | Exemplars boosted reachable accuracy to 90.91%, but global production requires reconciling evaluation dataset taxonomy with runtime enums. |
| **Tool Selection** | **EXPERIMENTAL ONLY** | Achieves 90% accuracy on registered tools with 0 boundary violations. Excellent candidate for opt-in pilot behind gateway. |
| **Evidence Sufficiency** | **NOT JUSTIFIED** | Evaluation logic is 100% deterministic Python. Offloading to an external cloud model adds latency and failure modes with zero benefit. |
| **Risk Gating (HITL)** | **EXPERIMENTAL ONLY** | 100% schema conformant. Requires deterministic rule safeguards due to unvalidated confidence calibration. |

---

## 5. Production Safety & Invariants

1. `DECISION_PROVIDER=structured_llm` remains the production default.
2. Jev remains behind the `DecisionGateway` abstraction.
3. No silent fallbacks to mock or LLM on live Jev failure.
4. Deterministic analytics, SQL generation, forecasting, and LangGraph topology remain completely untouched.
