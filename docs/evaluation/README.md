# NEXUS Evaluation & Benchmarking Framework

## Overview
Phase 9 transforms NEXUS from a functional agentic prototype into a **measurable, testable, and verifiable intelligence system**.

Rather than relying on superficial heuristic grading or arbitrary "AI scores", the NEXUS evaluation framework measures correctness across every stage of the business intelligence pipeline:

```
User Business Question
          ↓
Intent Understanding & Classification
          ↓
Semantic Terminology Resolution & Disambiguation
          ↓
Business Context RAG Retrieval
          ↓
Deterministic Planning & Tool Selection
          ↓
Audit-Backed Analytics Execution
          ↓
Diagnostic Investigation & Price-Volume-Mix Decomposition
          ↓
Time Series Forecasting & Statistical Prediction Intervals
          ↓
Evidence Record & Provenance Verification
          ↓
Narrative Explanation & Causality Safeguards
```

---

## Directory Structure

```
evaluation/
├── datasets/
│   ├── golden_questions.json       # 35+ verified retail questions across 8 categories
│   ├── edge_cases.json             # Boundary conditions (empty data, missing periods, zero division)
│   └── adversarial_questions.json  # Injection attempts, mutation queries, and policy evasion
├── runner/
│   ├── __init__.py                 # Exported harness interfaces
│   ├── __main__.py                 # CLI entrypoint (python -m evaluation.runner)
│   ├── runner.py                   # Orchestrator and benchmark execution engine
│   ├── metrics.py                  # Multi-dimensional correctness & latency calculators
│   ├── evaluators.py               # Deterministic rule evaluators and rubric judges
│   ├── taxonomy.py                 # Standardized failure taxonomy (17 categories, 4 severities)
│   └── reporters.py                # JSON and Markdown report formatters
├── baselines/
│   └── phase9_baseline.json        # Reference stability baseline and regression rules
└── reports/
    ├── phase9_report.json          # Machine-readable evaluation telemetry
    └── phase9_report.md            # Human-readable executive & technical audit report
```

---

## Quickstart

Run all benchmark test cases and compare against baseline:
```bash
python -m evaluation.runner --compare-baseline
```

Filter by question archetype:
```bash
# Run only descriptive financial questions
python -m evaluation.runner --category descriptive

# Run only predictive forecasting inquiries
python -m evaluation.runner --category forecast

# Run only prompt-injection and security evaluations
python -m evaluation.runner --adversarial

# Run only boundary edge cases
python -m evaluation.runner --edge-cases
```

Establish or update the official regression baseline:
```bash
python -m evaluation.runner --all --generate-baseline
```

---

## Key Core Invariants
1. **Zero Fake Metrics**: Numerical accuracy is evaluated strictly against deterministic accounting formulas (with defined absolute and relative tolerances).
2. **Deterministic CI**: The test suite runs in 100% offline mode without requiring paid third-party LLM API keys.
3. **No Single Magic Score**: NEXUS reports a transparent matrix across Intent, Semantics, Tools, Numbers, Drivers, Evidence, Groundedness, Hallucination, and Latency.
4. **Strict Safety Gates**: Zero tolerance for prompt injection vulnerabilities, SQL execution attempts, or hallucinated claims.
