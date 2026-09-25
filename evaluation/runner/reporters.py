"""Reporting utilities to export evaluation results to structured JSON and Markdown."""

import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from evaluation.runner.metrics import EvaluationMetricsSummary
from evaluation.runner.taxonomy import EvaluationFailure


class EvaluationReporter:
    """Generates comprehensive, audit-ready JSON and Markdown evaluation reports."""

    @staticmethod
    def generate_json_report(
        summary: EvaluationMetricsSummary,
        failures: List[EvaluationFailure],
        case_results: List[Dict[str, Any]],
        regression_diff: Optional[Dict[str, Any]] = None,
        output_path: str = "evaluation/reports/phase9_report.json",
    ) -> str:
        """Serialize full evaluation telemetry and failure trace to JSON."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        report_data = {
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "system": "NEXUS Agentic Business Intelligence Platform",
                "phase": "Phase 9 — Evaluation & Benchmarking",
            },
            "summary": summary.model_dump(),
            "failures": [f.to_dict() for f in failures],
            "regression_comparison": regression_diff or {},
            "case_results": case_results,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        return output_path

    @staticmethod
    def generate_markdown_report(
        summary: EvaluationMetricsSummary,
        failures: List[EvaluationFailure],
        regression_diff: Optional[Dict[str, Any]] = None,
        output_path: str = "evaluation/reports/phase9_report.md",
    ) -> str:
        """Format an executive and technical Markdown report."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        lines = [
            "# NEXUS Phase 9 — Evaluation & Benchmarking Report",
            "",
            f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
            "**System:** NEXUS Agentic Business Intelligence Platform  ",
            "**Evaluation Harness:** Pipeline-Wide Multi-Dimensional Correctness",
            "",
            "---",
            "",
            "## 1. Executive Summary",
            "",
            f"- **Total Benchmark Cases:** {summary.total_cases}",
            f"- **Passed Cases:** {summary.passed_cases}",
            f"- **Failed Cases:** {summary.failed_cases}",
            f"- **Pass Rate:** **{summary.pass_rate:.1f}%**",
            "",
            "| Evaluation Dimension | Accuracy / Score | Benchmark Target | Status |",
            "| :--- | :--- | :--- | :--- |",
            f"| **Intent Classification** | {summary.intent_accuracy:.1f}% | ≥ 95.0% | {'✅ PASS' if summary.intent_accuracy >= 95 else '⚠️ REVIEW'} |",
            f"| **Semantic Resolution** | {summary.semantic_accuracy:.1f}% | ≥ 90.0% | {'✅ PASS' if summary.semantic_accuracy >= 90 else '⚠️ REVIEW'} |",
            f"| **Tool Selection** | {summary.tool_selection_accuracy:.1f}% | ≥ 95.0% | {'✅ PASS' if summary.tool_selection_accuracy >= 95 else '⚠️ REVIEW'} |",
            f"| **Numerical Accuracy (Exact Tolerance)** | {summary.numerical_accuracy:.1f}% | 100.0% | {'✅ PASS' if summary.numerical_accuracy == 100 else '⚠️ REVIEW'} |",
            f"| **Analytical Driver Coverage** | {summary.analytical_correctness:.1f}% | ≥ 85.0% | {'✅ PASS' if summary.analytical_correctness >= 85 else '⚠️ REVIEW'} |",
            f"| **Evidence Completeness** | {summary.evidence_completeness:.1f}% | ≥ 90.0% | {'✅ PASS' if summary.evidence_completeness >= 90 else '⚠️ REVIEW'} |",
            f"| **Groundedness Score** | {summary.groundedness_score:.1f}% | ≥ 90.0% | {'✅ PASS' if summary.groundedness_score >= 90 else '⚠️ REVIEW'} |",
            f"| **Hallucination Rate** | {summary.hallucination_rate:.1f}% | ≤ 1.0% | {'✅ PASS' if summary.hallucination_rate <= 1.0 else '🚨 FAIL'} |",
            f"| **Adversarial / Injection Defense** | {summary.adversarial_defense_rate:.1f}% | 100.0% | {'✅ PASS' if summary.adversarial_defense_rate == 100 else '🚨 FAIL'} |",
            "",
            "---",
            "",
            "## 2. Latency Telemetry",
            "",
            f"- **Mean Latency:** {summary.latency_mean_ms:.1f} ms",
            f"- **Median Latency:** {summary.latency_median_ms:.1f} ms",
            f"- **P95 Latency:** {summary.latency_p95_ms:.1f} ms",
            "",
            "---",
            "",
            "## 3. Forecast Quality (Backtesting)",
            "",
            f"- **MAE (Mean Absolute Error):** {summary.forecast_mae if summary.forecast_mae is not None else 'N/A'}",
            f"- **RMSE (Root Mean Squared Error):** {summary.forecast_rmse if summary.forecast_rmse is not None else 'N/A'}",
            f"- **sMAPE (Symmetric MAPE):** {f'{summary.forecast_smape:.2f}%' if summary.forecast_smape is not None else 'N/A'}",
            "",
            "---",
            "",
            "## 4. Failure Taxonomy & Root Causes",
            "",
        ]

        if not failures:
            lines.append("✅ **Zero benchmark failures detected across all evaluation suites.**")
        else:
            lines.append("| Case ID | Category | Severity | Stage | Details |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for f in failures:
                lines.append(f"| `{f.case_id}` | `{f.category.value}` | `{f.severity.value}` | `{f.stage}` | {f.message} |")

        lines.extend([
            "",
            "---",
            "",
            "## 5. Regression Detection vs Baseline",
            "",
        ])

        if regression_diff:
            has_regression = regression_diff.get("has_regression", False)
            lines.append(f"**Regression Status:** {'🚨 REGRESSION DETECTED' if has_regression else '✅ STABLE / NO REGRESSIONS'}")
            lines.append("")
            for reg in regression_diff.get("details", []):
                lines.append(f"- {reg}")
        else:
            lines.append("No previous baseline compared (or baseline established in this run).")

        lines.extend([
            "",
            "---",
            "",
            "## 6. Known Weaknesses & Future Roadmap",
            "",
            "1. **Cold Start Data Requirements**: Forecasting requires a minimum of 6 historical periods for seasonal models; shorter series fall back gracefully to linear/moving average.",
            "2. **Ambiguous Terminology Without Domain**: Multi-domain terms (such as standalone 'turnover') require interactive clarification rather than aggressive assumption.",
            "3. **External Benchmarks**: Operational metrics outside the transactional retail schema (e.g. employee productivity, market share) are rejected safely.",
            "",
            "---",
            "*Report generated autonomously by NEXUS Evaluation Harness.*",
        ])

        report_content = "\n".join(lines)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        return output_path
