"""NEXUS Evaluation Runner Package."""

from evaluation.runner.taxonomy import FailureCategory, FailureSeverity, EvaluationFailure
from evaluation.runner.metrics import EvaluationMetricsSummary, compute_numerical_match
from evaluation.runner.evaluators import DeterministicEvaluator, LLMAssistedEvaluator
from evaluation.runner.reporters import EvaluationReporter
from evaluation.runner.runner import EvaluationRunner

__all__ = [
    "FailureCategory",
    "FailureSeverity",
    "EvaluationFailure",
    "EvaluationMetricsSummary",
    "compute_numerical_match",
    "DeterministicEvaluator",
    "LLMAssistedEvaluator",
    "EvaluationReporter",
    "EvaluationRunner",
]
