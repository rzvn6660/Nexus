"""Pydantic API response wrappers for NEXUS Analytics endpoints."""

from typing import Generic, TypeVar, Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.analytics.core.models import (
    FinancialSummaryResult,
    ProductPerformanceItem,
    BreakdownResult,
    TimeSeriesResult,
    CustomerRFMRecord,
    RepeatPurchaseResult,
    VarianceAnalysisResult,
    PriceVolumeMixDecomposition,
    CorrelationResult,
    StatisticalTestResult,
)
from app.analytics.customer.rfm import RFMAnalysisSummary
from app.analytics.customer.cohorts import CohortAnalysisResult
from app.analytics.inventory.stock import InventoryOverviewResult
from app.analytics.inventory.turnover import InventoryTurnoverResult
from app.analytics.metrics.expenses import ExpenseAnalysisResult
from app.analytics.evidence.models import EvidenceRecord

T = TypeVar("T")


class AnalyticsEnvelope(BaseModel, Generic[T]):
    """Standardized response container pairing deterministic results with full audit evidence."""
    success: bool = Field(default=True)
    data: T
    evidence: EvidenceRecord


# Typed response envelopes for clean OpenAPI schema generation
SummaryResponse = AnalyticsEnvelope[FinancialSummaryResult]
ProductRankingResponse = AnalyticsEnvelope[List[ProductPerformanceItem]]
BreakdownResponse = AnalyticsEnvelope[BreakdownResult]
TimeSeriesResponse = AnalyticsEnvelope[TimeSeriesResult]
RFMResponse = AnalyticsEnvelope[RFMAnalysisSummary]
CohortResponse = AnalyticsEnvelope[CohortAnalysisResult]
RepeatPurchaseResponse = AnalyticsEnvelope[RepeatPurchaseResult]
InventoryOverviewResponse = AnalyticsEnvelope[InventoryOverviewResult]
InventoryTurnoverResponse = AnalyticsEnvelope[InventoryTurnoverResult]
ExpenseResponse = AnalyticsEnvelope[ExpenseAnalysisResult]
VarianceResponse = AnalyticsEnvelope[VarianceAnalysisResult]
DecompositionResponse = AnalyticsEnvelope[PriceVolumeMixDecomposition]
CorrelationResponse = AnalyticsEnvelope[CorrelationResult]
StatisticalTestResponse = AnalyticsEnvelope[StatisticalTestResult]
