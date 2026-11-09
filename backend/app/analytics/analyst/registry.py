"""Central Reusable Skill Registry for the NEXUS Adaptive Analyst Engine."""

from typing import Dict, List, Optional
from app.analytics.analyst.base import BaseAnalystSkill
from app.analytics.analyst.models import SkillDomain, SkillMetadata
from app.analytics.analyst.skills.commercial import (
    CommercialForecastingSkill,
    GrossMarginAnalysisSkill,
    KPIDecompositionSkill,
    ProductProfitabilitySkill,
    RevenuePerformanceSkill,
    SalesTrendAnalysisSkill,
)
from app.analytics.analyst.skills.customer import (
    CustomerCohortSkill,
    CustomerConcentrationSkill,
    CustomerLTVMetricSkill,
    ProductAffinitySkill,
    PurchaseCadenceSkill,
    RepeatPurchaseSkill,
    RFMSegmentationSkill,
)
from app.analytics.analyst.skills.diagnostic import (
    AnomalyDetectionSkill,
    ContributionAnalysisSkill,
    DriverAnalysisSkill,
    MarginVarianceSkill,
    ProductCategoryPerformanceSkill,
    RevenueVarianceSkill,
)
from app.analytics.analyst.skills.discovery import (
    DataProfilingSkill,
    DescriptiveStatisticsSkill,
    DistributionAnalysisSkill,
    ExploratoryDataAnalysisSkill,
    MissingValueAnalysisSkill,
    RelationshipDiscoverySkill,
)
from app.analytics.analyst.skills.predictive import (
    BacktestingSkill,
    ChurnPredictionSkill,
    ConfidenceIntervalsSkill,
    ModelValidationSkill,
    RegressionAnalysisSkill,
    SeasonalityAnalysisSkill,
    TimeSeriesForecastingSkill,
)
from app.analytics.analyst.skills.quality import (
    DataProvenanceSkill,
    DuplicateDetectionSkill,
    OutlierInvestigationSkill,
    ReconciliationAuditSkill,
    ReferentialIntegritySkill,
    SchemaValidationSkill,
    SourceCompletenessSkill,
)
from app.analytics.analyst.skills.reporting import (
    AutomatedInsightSkill,
    BusinessQuestionAnsweringSkill,
    DecisionImpactSummariesSkill,
    EvidenceBackedRecommendationsSkill,
    ExecutiveSummarySkill,
    ManagementReportCompositionSkill,
)
from app.analytics.analyst.skills.retention import (
    ABTestAnalysisSkill,
    IncrementalityMeasurementSkill,
    InterventionRecommendationSkill,
    RetentionOpportunitySkill,
    RetentionOutcomeMeasurementSkill,
    UpliftEstimationSkill,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class AnalystSkillRegistry:
    """Singleton repository managing all registered analyst skills, versions, and activation states."""

    _instance: Optional["AnalystSkillRegistry"] = None

    def __init__(self) -> None:
        self._skills: Dict[str, BaseAnalystSkill] = {}
        self._bootstrap_default_skills()

    @classmethod
    def get_instance(cls) -> "AnalystSkillRegistry":
        if cls._instance is None:
            cls._instance = AnalystSkillRegistry()
        return cls._instance

    def _bootstrap_default_skills(self) -> None:
        """Instantiate and register all default specialist skills across 8 domains."""
        default_skills = [
            # Family A: Data Discovery and Exploration
            DataProfilingSkill(),
            DistributionAnalysisSkill(),
            MissingValueAnalysisSkill(),
            RelationshipDiscoverySkill(),
            DescriptiveStatisticsSkill(),
            ExploratoryDataAnalysisSkill(),
            # Family B: Data Quality and Governance
            SchemaValidationSkill(),
            DuplicateDetectionSkill(),
            ReferentialIntegritySkill(),
            ReconciliationAuditSkill(),
            OutlierInvestigationSkill(),
            SourceCompletenessSkill(),
            DataProvenanceSkill(),
            # Family C: Customer and Revenue Analytics
            RFMSegmentationSkill(),
            CustomerCohortSkill(),
            RepeatPurchaseSkill(),
            CustomerLTVMetricSkill(),
            PurchaseCadenceSkill(),
            ProductAffinitySkill(),
            CustomerConcentrationSkill(),
            # Family D: Predictive and Statistical Analytics
            ChurnPredictionSkill(),
            TimeSeriesForecastingSkill(),
            RegressionAnalysisSkill(),
            ConfidenceIntervalsSkill(),
            ModelValidationSkill(),
            BacktestingSkill(),
            SeasonalityAnalysisSkill(),
            # Family E: Diagnostic and Root Cause Analytics
            RevenueVarianceSkill(),
            MarginVarianceSkill(),
            AnomalyDetectionSkill(),
            DriverAnalysisSkill(),
            ContributionAnalysisSkill(),
            ProductCategoryPerformanceSkill(),
            # Family F: Retention and Experimentation
            RetentionOpportunitySkill(),
            InterventionRecommendationSkill(),
            ABTestAnalysisSkill(),
            UpliftEstimationSkill(),
            IncrementalityMeasurementSkill(),
            RetentionOutcomeMeasurementSkill(),
            # Family G: Commercial and Financial Analytics
            RevenuePerformanceSkill(),
            GrossMarginAnalysisSkill(),
            SalesTrendAnalysisSkill(),
            ProductProfitabilitySkill(),
            KPIDecompositionSkill(),
            CommercialForecastingSkill(),
            # Family H: Reporting and Decision Intelligence
            ExecutiveSummarySkill(),
            AutomatedInsightSkill(),
            EvidenceBackedRecommendationsSkill(),
            ManagementReportCompositionSkill(),
            BusinessQuestionAnsweringSkill(),
            DecisionImpactSummariesSkill(),
        ]

        for s in default_skills:
            self.register_skill(s)

        logger.info(f"AnalystSkillRegistry initialized with {len(self._skills)} specialist skills.")

    def register_skill(self, skill: BaseAnalystSkill) -> None:
        self._skills[skill.skill_id] = skill

    def get_skill(self, skill_id: str) -> Optional[BaseAnalystSkill]:
        return self._skills.get(skill_id)

    def list_skills(self, domain: Optional[SkillDomain] = None) -> List[SkillMetadata]:
        """List metadata for all registered skills, optionally filtered by domain."""
        skills = self._skills.values()
        if domain:
            skills = [s for s in skills if s.domain == domain]
        return [s.metadata for s in skills]

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> bool:
        skill = self._skills.get(skill_id)
        if skill:
            skill.set_enabled(enabled)
            return True
        return False

    def count(self) -> int:
        return len(self._skills)


# Global access function
def get_skill_registry() -> AnalystSkillRegistry:
    return AnalystSkillRegistry.get_instance()
