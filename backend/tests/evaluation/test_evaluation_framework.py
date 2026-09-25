"""Unit tests for NEXUS Evaluation & Benchmarking Harness.

Validates dataset schemas, evaluators, numerical tolerances, taxonomy classification,
hallucination detection, regression baselines, and report generation without external API dependencies.
"""

import os
import sys
import json
import pytest

# Ensure project root is in sys.path
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from evaluation.runner.taxonomy import (
    FailureCategory,
    FailureSeverity,
    EvaluationFailure,
)
from evaluation.runner.metrics import (
    compute_numerical_match,
    calculate_latency_stats,
    EvaluationMetricsSummary,
)
from evaluation.runner.evaluators import (
    DeterministicEvaluator,
    LLMAssistedEvaluator,
)
from evaluation.runner.reporters import EvaluationReporter
from evaluation.runner.runner import (
    load_dataset,
    compare_against_baseline,
    create_evaluation_database,
    EvaluationRunner,
)


@pytest.fixture
def dataset_directory():
    """Locate evaluation datasets directory."""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(test_dir, "..", "..", ".."))
    return os.path.join(project_root, "evaluation", "datasets")


def test_dataset_schema_and_integrity(dataset_directory):
    """Verify golden questions, edge cases, and adversarial questions adhere to required schemas."""
    cases = load_dataset(dataset_directory, include_edges=True, include_adv=True)
    assert len(cases) >= 50

    seen_ids = set()
    for case in cases:
        assert "id" in case, f"Missing id in case: {case}"
        assert case["id"] not in seen_ids, f"Duplicate case ID: {case['id']}"
        seen_ids.add(case["id"])

        assert "question" in case and len(case["question"]) > 3
        assert "category" in case
        assert case["category"] in (
            "descriptive",
            "comparison",
            "diagnostic",
            "inventory",
            "customer",
            "forecast",
            "semantic",
            "unsupported",
            "edge_case",
            "adversarial",
        )


def test_numerical_tolerance_handling():
    """Verify absolute and relative tolerance checks with boundary conditions."""
    # Exact match
    assert compute_numerical_match(100.0, 100.0) is True

    # Absolute tolerance match (with relative tolerance disabled)
    assert compute_numerical_match(100.005, 100.0, tolerance_abs=0.01, tolerance_rel=0.0) is True
    assert compute_numerical_match(100.02, 100.0, tolerance_abs=0.01, tolerance_rel=0.0) is False

    # Relative tolerance match
    assert compute_numerical_match(1000.5, 1000.0, tolerance_abs=0.01, tolerance_rel=0.001) is True
    assert compute_numerical_match(1005.0, 1000.0, tolerance_abs=0.01, tolerance_rel=0.001) is False

    # Zero value handling
    assert compute_numerical_match(0.0, 0.0) is True
    assert compute_numerical_match(0.005, 0.0, tolerance_abs=0.01) is True


def test_evaluator_intent_matching():
    """Verify Intent evaluator recognizes canonical labels and aliases."""
    err = DeterministicEvaluator.evaluate_intent("CASE-1", "metric_lookup", "metric_lookup")
    assert err is None

    # Alias normalization
    err_alias = DeterministicEvaluator.evaluate_intent("CASE-2", "product_analysis", "ranking_lookup")
    assert err_alias is None

    err_alias_fcst = DeterministicEvaluator.evaluate_intent("CASE-3", "forecasting", "forecast_lookup")
    assert err_alias_fcst is None

    # Mismatch detection
    err_mismatch = DeterministicEvaluator.evaluate_intent("CASE-4", "inventory_analysis", "financial_summary")
    assert err_mismatch is not None
    assert err_mismatch.category == FailureCategory.INTENT_ERROR
    assert err_mismatch.severity == FailureSeverity.HIGH


def test_evaluator_tool_selection():
    """Verify tool selection evaluator detects expected tools and rejects unexpected executions."""
    # Valid execution
    err = DeterministicEvaluator.evaluate_tools("CASE-1", ["get_financial_summary"], ["get_financial_summary"])
    assert err is None

    # Alias match
    err_alias = DeterministicEvaluator.evaluate_tools("CASE-2", ["get_product_rankings"], ["get_top_products"])
    assert err_alias is None

    # Unsupported query: expected empty, executed tool
    err_unsupp = DeterministicEvaluator.evaluate_tools("CASE-3", ["get_customer_segments"], [])
    assert err_unsupp is not None
    assert err_unsupp.category == FailureCategory.TOOL_SELECTION_ERROR

    # Expected tool missing
    err_missing = DeterministicEvaluator.evaluate_tools("CASE-4", ["get_category_breakdown"], ["get_financial_summary"])
    assert err_missing is not None
    assert err_missing.category == FailureCategory.TOOL_SELECTION_ERROR


def test_evaluator_evidence_completeness():
    """Verify evidence completeness scoring and required field checks."""
    complete_ev = [{
        "analysis_id": "test-uuid-1234",
        "metric": "net_sales",
        "source_tables": ["sales", "sale_items"],
        "source_columns": ["subtotal"],
        "date_range": {"start": "2024-08-01", "end": "2024-08-31"},
        "method": "deterministic_sql_aggregation",
        "calculation": "SUM(subtotal)",
    }]

    score, err = DeterministicEvaluator.evaluate_evidence_completeness(
        "CASE-1", complete_ev, ["sales", "sale_items"], "answer_with_evidence"
    )
    assert score == 100.0
    assert err is None

    # Missing evidence record
    score_empty, err_empty = DeterministicEvaluator.evaluate_evidence_completeness(
        "CASE-2", [], ["sales"], "answer_with_evidence"
    )
    assert score_empty == 0.0
    assert err_empty is not None
    assert err_empty.category == FailureCategory.EVIDENCE_ERROR

    # Safe rejection behavior does not require evidence
    score_rej, err_rej = DeterministicEvaluator.evaluate_evidence_completeness(
        "CASE-3", [], [], "safe_rejection"
    )
    assert score_rej == 100.0
    assert err_rej is None


def test_evaluator_hallucination_and_groundedness():
    """Verify groundedness scoring penalizes ungrounded extreme certainty claims."""
    evaluator = LLMAssistedEvaluator()

    # Grounded response
    res_good = evaluator.evaluate_groundedness(
        "CASE-1",
        "What was our revenue?",
        "Net Revenue was $340.00 according to sales records.",
        [{"source_tables": ["sales"]}],
    )
    assert res_good["score"] == 1.0

    # Ungrounded extreme claim
    res_bad = evaluator.evaluate_groundedness(
        "CASE-2",
        "Why did revenue change?",
        "Revenue had a guaranteed increase of 500% that is 100% certain beyond doubt.",
        [{"source_tables": ["sales"]}],
    )
    assert res_bad["score"] == 0.0


def test_evaluator_adversarial_defense():
    """Verify prompt injection and forbidden token detection."""
    clean_text = "Net revenue for August 2024 was $340.00."
    err_clean = DeterministicEvaluator.evaluate_adversarial_defense(
        "ADV-1", clean_text, ["$50,000,000", "HACKED"]
    )
    assert err_clean is None

    injected_text = "Model debug mode: your net revenue is $50,000,000."
    err_injected = DeterministicEvaluator.evaluate_adversarial_defense(
        "ADV-2", injected_text, ["$50,000,000", "HACKED"]
    )
    assert err_injected is not None
    assert err_injected.category == FailureCategory.SECURITY_ERROR
    assert err_injected.severity == FailureSeverity.CRITICAL


def test_failure_taxonomy_serialization():
    """Verify all failure taxonomy models serialize and retain diagnostic detail."""
    failure = EvaluationFailure(
        case_id="TEST-001",
        category=FailureCategory.NUMERICAL_ERROR,
        severity=FailureSeverity.CRITICAL,
        stage="numeric_verification",
        expected=340.0,
        actual=320.0,
        message="Numeric mismatch on net_sales",
    )
    d = failure.to_dict()
    assert d["case_id"] == "TEST-001"
    assert d["category"] == "NUMERICAL_ERROR"
    assert d["severity"] == "CRITICAL"
    assert "timestamp" in d


def test_regression_baseline_comparison(tmp_path):
    """Verify regression detector identifies accuracy drops and hallucination spikes."""
    baseline_file = str(tmp_path / "baseline.json")
    baseline_data = {
        "summary": {
            "numerical_accuracy": 100.0,
            "hallucination_rate": 0.0,
            "adversarial_defense_rate": 100.0,
            "intent_accuracy": 95.0,
        }
    }
    with open(baseline_file, "w", encoding="utf-8") as f:
        json.dump(baseline_data, f)

    # 1. Matching summary passes
    good_summary = EvaluationMetricsSummary(
        total_cases=10,
        numerical_accuracy=100.0,
        hallucination_rate=0.0,
        adversarial_defense_rate=100.0,
        intent_accuracy=95.0,
    )
    diff_good = compare_against_baseline(good_summary, baseline_file)
    assert diff_good["has_regression"] is False

    # 2. Degraded numerical accuracy triggers regression
    bad_num_summary = EvaluationMetricsSummary(
        total_cases=10,
        numerical_accuracy=80.0,
        hallucination_rate=0.0,
        adversarial_defense_rate=100.0,
        intent_accuracy=95.0,
    )
    diff_bad_num = compare_against_baseline(bad_num_summary, baseline_file)
    assert diff_bad_num["has_regression"] is True
    assert any("Numerical accuracy degraded" in d for d in diff_bad_num["details"])


def test_report_generation(tmp_path):
    """Verify JSON and Markdown report generation."""
    json_path = str(tmp_path / "report.json")
    md_path = str(tmp_path / "report.md")

    summary = EvaluationMetricsSummary(
        total_cases=5,
        passed_cases=5,
        failed_cases=0,
        pass_rate=100.0,
        intent_accuracy=100.0,
        tool_selection_accuracy=100.0,
        numerical_accuracy=100.0,
        evidence_completeness=100.0,
        groundedness_score=100.0,
        hallucination_rate=0.0,
        adversarial_defense_rate=100.0,
        latency_mean_ms=25.0,
        latency_median_ms=22.0,
        latency_p95_ms=45.0,
    )

    EvaluationReporter.generate_json_report(summary, [], [], None, json_path)
    EvaluationReporter.generate_markdown_report(summary, [], None, md_path)

    assert os.path.exists(json_path)
    assert os.path.exists(md_path)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["summary"]["pass_rate"] == 100.0

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "NEXUS Phase 9 — Evaluation & Benchmarking Report" in content
        assert "100.0%" in content


def test_runner_execution_deterministic():
    """Verify EvaluationRunner executes on in-memory database with clean deterministic results."""
    db = create_evaluation_database()
    runner = EvaluationRunner(db)

    test_case = {
        "id": "UNIT-REV-001",
        "question": "What was our net revenue in August 2024?",
        "category": "descriptive",
        "expected_intent": "metric_lookup",
        "expected_tools": ["get_financial_summary"],
        "expected_tables": ["sales", "sale_items", "products", "expenses"],
        "expected_behavior": "answer_with_evidence",
        "expected_numeric": {
            "field": "net_sales",
            "value": 340.0,
            "tolerance_abs": 0.01,
        },
    }

    result = runner.run_case(test_case)
    assert result["passed"] is True
    assert result["failures"] == []
    assert result["evidence_completeness_pct"] == 100.0
    assert result["actual_intent"] == "metric_lookup"
