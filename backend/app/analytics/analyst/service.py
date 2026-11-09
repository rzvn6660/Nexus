"""Unified Facade Service for the NEXUS Adaptive Analyst Engine."""

from typing import Any, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.analyst.lead_analyst import LeadAnalyst, LeadAnalystReport
from app.analytics.analyst.ledger import AnalystEvidenceLedger
from app.analytics.analyst.models import ExecutionContext, SkillDomain, SkillMetadata
from app.analytics.analyst.orchestrator import (
    AnalystOrchestrator,
    ExecutionPlan,
    OrchestrationResult,
)
from app.analytics.analyst.registry import AnalystSkillRegistry, get_skill_registry
from app.core.logging import get_logger
from app.models.history import AnalysisRun
from app.models.sale import Sale

logger = get_logger(__name__)


class AnalystService:
    """Primary facade coordinating Skill Registry, Orchestrator, Lead Analyst, and Evidence Ledger."""

    @classmethod
    def get_overview(cls, db: Session, business_id: str) -> Dict[str, Any]:
        """Aggregate high-level telemetry for the Analyst Studio overview workspace."""
        registry = get_skill_registry()
        all_skills = registry.list_skills()
        active_skills = [s for s in all_skills if s.enabled]

        # Count historical runs
        total_runs = (
            db.execute(
                select(func.count(AnalysisRun.id)).where(AnalysisRun.business_id == business_id)
            ).scalar()
            or 0
        )

        completed_runs = (
            db.execute(
                select(func.count(AnalysisRun.id)).where(
                    AnalysisRun.business_id == business_id,
                    AnalysisRun.status == "completed",
                )
            ).scalar()
            or 0
        )

        success_rate = (completed_runs / total_runs * 100) if total_runs else 100.0

        # Check authoritative data readiness via TenantReadinessService
        from app.services.tenant_readiness_service import TenantReadinessService
        readiness_packet = TenantReadinessService.get_tenant_readiness(db, business_id)
        readiness_status = readiness_packet.readiness_status.value

        # Domain breakdown
        domain_counts: Dict[str, int] = {}
        for s in all_skills:
            d_val = s.domain.value
            domain_counts[d_val] = domain_counts.get(d_val, 0) + 1

        recent_runs = AnalystEvidenceLedger.list_runs(db, business_id, limit=5)

        return {
            "total_registered_skills": len(all_skills),
            "active_skill_versions": len(active_skills),
            "total_analysis_runs": total_runs,
            "success_rate_pct": round(success_rate, 1),
            "data_readiness_status": readiness_status,
            "current_workload": "READY",
            "skills_by_domain": domain_counts,
            "recent_runs": recent_runs,
        }

    @classmethod
    def analyze_business_question(
        cls,
        db: Session,
        business_id: str,
        query: str,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        End-to-end execution:
        1. Query intent understanding & skill plan construction
        2. Specialist skill orchestration with dependency passing
        3. Lead Analyst reconciliation & 8-part synthesis
        4. Append-only Evidence Ledger persistence
        """
        registry = get_skill_registry()
        orchestrator = AnalystOrchestrator(registry)

        # 1. Build plan
        plan = orchestrator.build_plan(query)

        # 2. Context setup
        context = ExecutionContext(
            business_id=business_id,
            organization_id=organization_id,
            user_id=user_id,
            query=query,
        )

        # 3. Execute skills
        orchestration_result = orchestrator.execute_plan(db, plan, context)

        # 4. Lead Analyst Synthesis
        lead_report = LeadAnalyst.reconcile_and_synthesize(orchestration_result, context)

        # 5. Persist run to Evidence Ledger
        run_record = AnalystEvidenceLedger.record_run(
            db, context, orchestration_result, lead_report
        )

        return {
            "run_id": run_record.id,
            "request_id": run_record.request_id,
            "query": query,
            "intent": plan.detected_intent,
            "execution_plan": plan.model_dump(),
            "lead_analyst_report": lead_report.model_dump(),
            "skills_used": plan.selected_skill_ids,
            "execution_time_ms": orchestration_result.total_execution_time_ms,
            "data_readiness": orchestration_result.data_readiness,
        }

    @classmethod
    def list_skills(cls, domain: Optional[SkillDomain] = None) -> List[SkillMetadata]:
        return get_skill_registry().list_skills(domain)

    @classmethod
    def toggle_skill(cls, skill_id: str, enabled: bool) -> bool:
        return get_skill_registry().set_skill_enabled(skill_id, enabled)

    @classmethod
    def list_runs(cls, db: Session, business_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return AnalystEvidenceLedger.list_runs(db, business_id, limit)

    @classmethod
    def get_run_detail(cls, db: Session, business_id: str, run_id: int) -> Optional[Dict[str, Any]]:
        return AnalystEvidenceLedger.get_run_detail(db, business_id, run_id)
