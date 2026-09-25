"""Evaluation metrics calculation for NEXUS intelligence pipeline."""

from typing import List, Dict, Any, Optional
import numpy as np
from pydantic import BaseModel, Field


class EvaluationMetricsSummary(BaseModel):
    """Aggregated evaluation metrics matrix across benchmark suites."""
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    pass_rate: float = 0.0

    # Dimension accuracies (0.0 - 100.0%)
    intent_accuracy: float = 0.0
    semantic_accuracy: float = 0.0
    tool_selection_accuracy: float = 0.0
    numerical_accuracy: float = 0.0
    analytical_correctness: float = 0.0
    evidence_completeness: float = 0.0
    groundedness_score: float = 0.0
    hallucination_rate: float = 0.0
    adversarial_defense_rate: float = 0.0

    # Forecast quality (out of sample backtesting)
    forecast_mae: Optional[float] = None
    forecast_rmse: Optional[float] = None
    forecast_smape: Optional[float] = None

    # Latency telemetry (in milliseconds)
    latency_mean_ms: float = 0.0
    latency_median_ms: float = 0.0
    latency_p95_ms: float = 0.0

    # Token & cost telemetry
    total_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    cost_status: str = "not_available"

    # Category breakdown
    category_metrics: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


def compute_numerical_match(
    actual_value: float | int,
    expected_value: float | int,
    tolerance_abs: float = 0.01,
    tolerance_rel: float = 0.001,
) -> bool:
    """
    Check if actual value matches expected within absolute or relative tolerance.
    Never uses vague grading for deterministic numeric outputs.
    """
    try:
        act = float(actual_value)
        exp = float(expected_value)
    except (ValueError, TypeError):
        return False

    abs_diff = abs(act - exp)
    if abs_diff <= tolerance_abs:
        return True

    if abs(exp) > 1e-9:
        rel_diff = abs_diff / abs(exp)
        if rel_diff <= tolerance_rel:
            return True

    return False


def calculate_latency_stats(latencies_ms: List[float]) -> Dict[str, float]:
    """Compute mean, median, and p95 latency from execution timings."""
    if not latencies_ms:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0}

    arr = np.array(latencies_ms, dtype=np.float64)
    return {
        "mean": float(round(np.mean(arr), 2)),
        "median": float(round(np.median(arr), 2)),
        "p95": float(round(np.percentile(arr, 95), 2)),
    }
