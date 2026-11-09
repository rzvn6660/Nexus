"""Central Automatic Skill Orchestrator for NEXUS Adaptive Analyst Engine."""

import time

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.analytics.analyst.models import (
    ExecutionContext,
    SkillExecutionResult,
)
from app.analytics.analyst.registry import AnalystSkillRegistry, get_skill_registry
from app.core.logging import get_logger

logger = get_logger(__name__)


class ExecutionPlan(BaseModel):
    """Dependency-aware plan detailing selected skills and routing rationale."""

    query: str
    detected_intent: str
    target_entities: list[str]
    selected_skill_ids: list[str]
    execution_order: list[str]
    routing_rationale: str
    created_at: float = Field(default_factory=time.time)


class ConflictRecord(BaseModel):
    """Discrepancy or conflicting finding between two or more analyst skills."""

    conflict_type: str
    skills_involved: list[str]
    description: str
    resolution_strategy: str


class OrchestrationResult(BaseModel):
    """Complete result packet produced by the orchestrator before Lead Analyst synthesis."""

    plan: ExecutionPlan
    skill_results: dict[str, SkillExecutionResult]
    conflicts: list[ConflictRecord]
    total_execution_time_ms: float
    data_readiness: str = "VERIFIED"


class AnalystOrchestrator:
    """Orchestrates specialist analyst skills based on natural language queries or analytical tasks."""

    def __init__(self, registry: AnalystSkillRegistry | None = None) -> None:
        self.registry = registry or get_skill_registry()

    def build_plan(self, query: str) -> ExecutionPlan:
        """Analyze business question and construct dynamic, dependency-aware skill execution plan."""
        q = query.lower().replace("-", " ").strip()

        # 1. Intent Detection
        if any(
            w in q
            for w in [
                "churn",
                "stop buying",
                "stop purchasing",
                "leave",
                "attrition",
                "dormant",
                "at risk",
                "salvage",
                "retention",
            ]
        ):
            intent = "CHURN_AND_RETENTION_INVESTIGATION"
            entities = ["Customer", "Sale"]
            skills = [
                "schema_validation",
                "purchase_cadence_analysis",
                "rfm_segmentation",
                "churn_prediction",
                "retention_opportunity_identification",
                "intervention_recommendation",
                "executive_summary_generation",
            ]
            rationale = "Query inquires about customer attrition. Routed through Data Quality, Cadence, RFM, Churn Prediction, and Retention Intervention Advisors."

        elif any(
            w in q
            for w in [
                "forecast",
                "forecasting",
                "predict",
                "next quarter",
                "future sales",
                "projection",
                "run rate",
                "sales be",
            ]
        ):
            intent = "COMMERCIAL_FORECASTING"
            entities = ["Sale"]
            skills = [
                "schema_validation",
                "revenue_performance",
                "time_series_forecasting",
                "seasonality_analysis",
                "confidence_intervals",
                "commercial_forecasting",
                "executive_summary_generation",
            ]
            rationale = "Query requests future revenue projections. Routed through Time-Series Forecaster, Seasonality, Confidence Bounds, and Commercial Run-Rate."

        elif any(
            w in q for w in ["why", "decrease", "drop", "fell", "down", "variance", "root cause"]
        ):
            intent = "REVENUE_VARIANCE_ROOT_CAUSE"
            entities = ["Sale", "Customer", "Product"]
            skills = [
                "schema_validation",
                "revenue_performance",
                "revenue_variance_decomposition",
                "anomaly_detection",
                "driver_analysis",
                "seasonality_analysis",
                "executive_summary_generation",
            ]
            rationale = "Query investigates revenue decline. Routed through Data Quality, Commercial Performance, Variance Decomposition (Price vs Volume), Anomaly Detection, and Segment Drivers."

        elif any(
            w in q
            for w in [
                "ad spend",
                "cac",
                "roas",
                "tiktok",
                "google ads",
                "facebook ads",
                "payroll",
                "employee",
                "salary",
                "weather",
                "competitor",
            ]
        ):
            intent = "UNSUPPORTED_OR_EXTERNAL_DATA_QUERY"
            entities = ["ExternalSource", "UnmodeledEntity"]
            skills = [
                "schema_validation",
                "source_completeness",
                "missing_value_analysis",
                "executive_summary_generation",
            ]
            rationale = "Query inquires about unmodeled external domain data (e.g., ad spend, marketing CAC, payroll, competitor pricing). Routed to Quality and Completeness skills to audit missing external data."

        elif any(
            w in q
            for w in [
                "margin",
                "profit",
                "profitability",
                "unprofitable",
                "cogs",
                "cost",
                "loss",
                "losses",
            ]
        ):
            intent = "MARGIN_AND_PROFITABILITY_AUDIT"
            entities = ["Product", "SaleItem", "Sale"]
            skills = [
                "schema_validation",
                "gross_margin_analysis",
                "margin_variance_analysis",
                "product_profitability",
                "product_category_performance",
                "executive_summary_generation",
            ]
            rationale = "Query questions margins and profitability. Routed through Gross Margin, Cost Variance, SKU Profitability, and Catalog Performance."

        elif any(w in q for w in ["quality", "complete", "clean", "trust", "audit", "valid"]):
            intent = "DATA_QUALITY_AND_GOVERNANCE_AUDIT"
            entities = ["Sale", "Customer", "Product", "Watermark"]
            skills = [
                "schema_validation",
                "duplicate_detection",
                "referential_integrity",
                "reconciliation_audit",
                "source_completeness",
                "data_provenance_validation",
                "executive_summary_generation",
            ]
            rationale = "Query audits data reliability. Routed through Schema Validator, Duplicate Detector, Referential Integrity, Reconciliation, and Provenance Auditor."

        else:
            # General business performance overview
            intent = "GENERAL_BUSINESS_PERFORMANCE_AUDIT"
            entities = ["Sale", "Customer", "Product"]
            skills = [
                "data_profiling",
                "revenue_performance",
                "gross_margin_analysis",
                "repeat_purchase_analysis",
                "churn_prediction",
                "automated_insight_generation",
                "executive_summary_generation",
            ]
            rationale = "General business performance question. Routed across foundational Discovery, Commercial, Customer Loyalty, and Executive Summary skills."

        return ExecutionPlan(
            query=query,
            detected_intent=intent,
            target_entities=entities,
            selected_skill_ids=skills,
            execution_order=skills,
            routing_rationale=rationale,
        )

    def execute_plan(
        self,
        db: Session,
        plan: ExecutionPlan,
        context: ExecutionContext,
    ) -> OrchestrationResult:
        """Topological execution of selected skills with error containment and conflict detection."""
        start_time = time.perf_counter()
        results: dict[str, SkillExecutionResult] = {}
        conflicts: list[ConflictRecord] = []

        for skill_id in plan.execution_order:
            skill = self.registry.get_skill(skill_id)
            if not skill:
                logger.warning(f"Skill '{skill_id}' not found in registry; skipping.")
                continue

            # Pass accumulated prior results to context
            context.prior_results = results
            res = skill.run(db, context)
            results[skill_id] = res

        # Conflict Detection between executed skills
        if "revenue_variance_decomposition" in results and "revenue_performance" in results:
            var_data = results["revenue_variance_decomposition"].data
            delta_rev = var_data.get("delta_revenue", 0)
            if "decrease" in plan.query.lower() and delta_rev > 0:
                conflicts.append(
                    ConflictRecord(
                        conflict_type="PREMISE_CONTRADICTION",
                        skills_involved=["revenue_performance", "revenue_variance_decomposition"],
                        description=f"User asked why revenue decreased, but 30-day sequential revenue actually increased by ${delta_rev:+,.2f}.",
                        resolution_strategy="Lead Analyst will clarify actual positive trend and highlight period boundaries.",
                    )
                )

        total_elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        from app.services.tenant_readiness_service import TenantReadinessService
        readiness_packet = TenantReadinessService.get_tenant_readiness(db, context.business_id)
        data_readiness = readiness_packet.readiness_status.value

        return OrchestrationResult(
            plan=plan,
            skill_results=results,
            conflicts=conflicts,
            total_execution_time_ms=round(total_elapsed_ms, 2),
            data_readiness=data_readiness,
        )
