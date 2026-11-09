"""Lead Analyst and Evidence Ledger Persistence Service."""

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.analytics.analyst.lead_analyst import LeadAnalystReport
from app.analytics.analyst.models import ExecutionContext
from app.analytics.analyst.orchestrator import OrchestrationResult
from app.core.logging import get_logger
from app.models.history import AnalysisRun

logger = get_logger(__name__)


class AnalystEvidenceLedger:
    """Persists immutable analysis runs, skill DAGs, calculations, and Lead Analyst reports into AnalysisRun."""

    @classmethod
    def record_run(
        cls,
        db: Session,
        context: ExecutionContext,
        orchestration: OrchestrationResult,
        report: LeadAnalystReport,
    ) -> AnalysisRun:
        """Commit an immutable audit record for an executed analysis run."""
        request_id = str(uuid4())
        plan = orchestration.plan

        # Assemble comprehensive evidence payload
        evidence_packet = {
            "execution_plan": plan.model_dump(),
            "skills_executed": [
                {
                    "skill_id": res.skill_id,
                    "skill_name": res.skill_name,
                    "domain": res.domain.value,
                    "status": res.status,
                    "confidence": res.confidence_score,
                    "latency_ms": res.execution_time_ms,
                    "findings": res.findings,
                    "calculations": res.calculations,
                    "limitations": res.limitations,
                }
                for res in orchestration.skill_results.values()
            ],
            "conflicts_detected": [c.model_dump() for c in orchestration.conflicts],
            "lead_analyst_synthesis": {
                "validation_status": report.validation_status,
                "confidence_score": report.confidence_score,
                "uncertainty_level": report.uncertainty_level,
                "confidence_rationale": report.confidence_rationale,
                "recommended_action": report.recommended_next_action,
            },
        }

        run = AnalysisRun(
            request_id=request_id,
            business_id=context.business_id,
            organization_id=context.organization_id,
            user_id=context.user_id,
            query=plan.query,
            intent=plan.detected_intent,
            status="completed",
            explanation_level="manager",
            answer=report.formatted_markdown,
            execution_time_ms=orchestration.total_execution_time_ms,
            tools_used=plan.selected_skill_ids,
            calculations=report.relevant_calculations,
            assumptions=["Data verified against committed tenant database state."],
            limitations=report.limitations,
            evidence_records=[evidence_packet],
        )

        db.add(run)
        db.commit()
        db.refresh(run)

        logger.info(f"Recorded analysis run {run.id} (request_id={request_id}) for business {context.business_id}.")
        return run

    @classmethod
    def list_runs(
        cls,
        db: Session,
        business_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List historical analysis runs for a tenant workspace."""
        runs = db.execute(
            select(AnalysisRun)
            .where(AnalysisRun.business_id == business_id)
            .order_by(desc(AnalysisRun.created_at))
            .limit(limit)
        ).scalars().all()

        results = []
        for r in runs:
            results.append({
                "id": r.id,
                "request_id": r.request_id,
                "query": r.query,
                "intent": r.intent,
                "status": r.status,
                "answer_preview": (r.answer[:160] + "...") if r.answer and len(r.answer) > 160 else r.answer,
                "tools_used": r.tools_used or [],
                "execution_time_ms": r.execution_time_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return results

    @classmethod
    def get_run_detail(
        cls,
        db: Session,
        business_id: str,
        run_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve full audit record, execution DAG, calculations, and evidence packet."""
        run = db.execute(
            select(AnalysisRun).where(AnalysisRun.id == run_id, AnalysisRun.business_id == business_id)
        ).scalar_one_or_none()

        if not run:
            return None

        evidence = run.evidence_records[0] if run.evidence_records else {}
        return {
            "id": run.id,
            "request_id": run.request_id,
            "business_id": run.business_id,
            "query": run.query,
            "intent": run.intent,
            "status": run.status,
            "answer": run.answer,
            "execution_time_ms": run.execution_time_ms,
            "tools_used": run.tools_used or [],
            "calculations": run.calculations or [],
            "limitations": run.limitations or [],
            "evidence": evidence,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        }
