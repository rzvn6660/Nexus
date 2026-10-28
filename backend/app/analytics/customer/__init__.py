"""Customer analytics package."""

from app.analytics.customer.cadence import (
    CadenceConfig,
    CadenceExplanation,
    CadenceRiskTier,
    CustomerCadenceAnalyzer,
    CustomerCadenceRecord,
    CustomerCadenceSummary,
)
from app.analytics.customer.cohorts import (
    CohortAnalysisResult,
    CohortCell,
    CohortRow,
    CustomerCohortAnalyzer,
)
from app.analytics.customer.readiness import (
    CustomerDataReadinessAssessor,
    CustomerDataReadinessReport,
    CutoffFeasibilityItem,
    DataQualityDiagnostics,
    HistoricalCoverageMetrics,
    IngestionHealthMetrics,
    PilotSafeguardsPolicy,
)
from app.analytics.customer.repeat_purchase import (
    RepeatPurchaseAnalyzer,
    RepeatPurchaseResult,
)
from app.analytics.customer.rfm import RFMAnalysisSummary, RFMAnalyzer
from app.analytics.customer.validation import (
    ConfusionMatrix,
    CustomerOutcomeRecord,
    CutoffEvaluationResult,
    HistoricalCadenceValidator,
    HistoricalValidationSummary,
    RiskTierPerformance,
)

__all__ = [
    "CadenceConfig",
    "CadenceExplanation",
    "CadenceRiskTier",
    "CohortAnalysisResult",
    "CohortCell",
    "CohortRow",
    "ConfusionMatrix",
    "CustomerCadenceAnalyzer",
    "CustomerCadenceRecord",
    "CustomerCadenceSummary",
    "CustomerCohortAnalyzer",
    "CustomerDataReadinessAssessor",
    "CustomerDataReadinessReport",
    "CustomerOutcomeRecord",
    "CutoffEvaluationResult",
    "CutoffFeasibilityItem",
    "DataQualityDiagnostics",
    "HistoricalCadenceValidator",
    "HistoricalCoverageMetrics",
    "HistoricalValidationSummary",
    "IngestionHealthMetrics",
    "PilotSafeguardsPolicy",
    "RFMAnalysisSummary",
    "RFMAnalyzer",
    "RepeatPurchaseAnalyzer",
    "RepeatPurchaseResult",
    "RiskTierPerformance",
]
