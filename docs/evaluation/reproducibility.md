# NEXUS Evaluation Reproducibility Guide

## 1. Zero-Dependency CI Design
To ensure that evaluation is reproducible in any local, CI, or containerized environment:
1. **Isolated In-Memory Fixtures**: The evaluation runner creates an isolated in-memory SQLite schema populated with 12 months of multi-period retail transactions.
2. **Deterministic Mock Layer**: Deterministic test providers ensure exact reproducibility without network dependencies or paid third-party API keys.
3. **No Flaky Assertions**: Numeric comparisons use bounded tolerances rather than fuzzy regex or LLM self-evaluation.

---

## 2. Step-by-Step Execution

### Run Full Pytest Suite (Unit + Evaluation Tests)
```bash
pytest backend/tests/ -q
```
Expected: `191 passed`.

### Run Standalone Evaluation Tests
```bash
pytest backend/tests/evaluation/test_evaluation_framework.py -v
```
Expected: `11 passed`.

### Run the Evaluation Harness and Check Against Baseline
```bash
python -m evaluation.runner --compare-baseline
```
Expected: `[BASELINE PASS] - All metric dimensions meet or exceed baseline stability thresholds.`

### Regenerate Baseline Metrics (When Authorized)
```bash
python -m evaluation.runner --all --generate-baseline
```

---

## 3. Regression Safeguards & Quality Gate Rules
A build is rejected under the following regression criteria:
- **Numerical Accuracy**: Must NOT decrease below baseline ($100.0\%$).
- **Hallucination Rate**: Must NOT increase above baseline ($0.0\%$).
- **Adversarial Defense**: Must NOT decrease below baseline ($100.0\%$).
- **Intent Accuracy**: Must NOT degrade by more than $5.0\%$ from baseline.
- **Evidence Completeness**: Must remain $\ge 90.0\%$.
