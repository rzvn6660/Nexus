"""Statistical analytics package."""

from app.analytics.statistics.descriptive import DescriptiveStatistics, DescriptiveStatsResult
from app.analytics.statistics.correlation import CorrelationAnalyzer
from app.analytics.statistics.hypothesis import HypothesisTestRunner
from app.analytics.statistics.regression import RegressionAnalyzer
from app.analytics.statistics.time_series_diagnostics import TimeSeriesDiagnosticAnalyzer
from app.analytics.statistics.pareto import ParetoAnalyzer
from app.analytics.statistics.selector import AnalyticalMethodSelector
from app.analytics.statistics.visual_analytics import ChartAdvisor
from app.analytics.statistics.normality import evaluate_normality, NormalityEvaluation
from app.analytics.statistics.multiple_testing import MultipleTestingCorrector, MultipleTestingResult

__all__ = [
    "DescriptiveStatistics",
    "DescriptiveStatsResult",
    "CorrelationAnalyzer",
    "HypothesisTestRunner",
    "RegressionAnalyzer",
    "TimeSeriesDiagnosticAnalyzer",
    "ParetoAnalyzer",
    "AnalyticalMethodSelector",
    "ChartAdvisor",
    "evaluate_normality",
    "NormalityEvaluation",
    "MultipleTestingCorrector",
    "MultipleTestingResult",
]
