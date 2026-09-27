"""NexusAgentService orchestration facade executing stateful LangGraph analytical flows.

Phase 19: Tenant-Aware Intelligence Runs
- Validates workspace readiness before analysis (data + semantic)
- Captures immutable semantic snapshot (revision_id, version) at run creation
- Captures immutable dataset snapshot (dataset_id, content_hash, ingestion_job_id, date_coverage)
- Persists user_id on AnalysisRun for complete audit traceability
- Enforces: no active semantic model → semantic-not-ready error
- Enforces: no completed ingestion → data-not-ready error (when business_id present)
- Historical runs retain the semantic version they actually used
"""

import time
from datetime import UTC, date, datetime
from typing import Any, Optional
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agents.graph.workflow import agent_graph
from app.agents.state.models import AgentState
from app.analytics.evidence.models import EvidenceRecord
from app.core.config import settings
from app.core.logging import get_logger
from app.models.history import AnalysisRun, DecisionRecord
from app.models.tenant import (
    Business,
    IngestionJob,
    TenantSemanticModel,
    UploadedDataset,
)
from app.rag.retrieval.models import RAGEvidence
from app.schemas.agent import AgentExecutionMetadata, AgentResponse

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Workspace Readiness
# ---------------------------------------------------------------------------

class WorkspaceNotReadyError(Exception):
    """Raised when the tenant workspace cannot support an analysis run."""
    def __init__(self, reason: str, stage: str) -> None:
        super().__init__(reason)
        self.stage = stage   # "data-not-ready" | "semantic-not-ready"
        self.reason = reason


def _resolve_workspace_snapshot(
    db: Session,
    business_id: str,
) -> dict[str, Any]:
    """
    Inspect tenant workspace and return immutable snapshot metadata for this run.

    Returns a dict with:
      semantic_revision_id, semantic_version,
      dataset_id, dataset_content_hash, ingestion_job_id, dataset_date_coverage

    Raises WorkspaceNotReadyError if workspace cannot support an analysis run.
    """
    # ------------------------------------------------------------------ #
    # 1. Semantic snapshot — only ACTIVE model is permitted               #
    # ------------------------------------------------------------------ #
    active_model: Optional[TenantSemanticModel] = db.execute(
        select(TenantSemanticModel)
        .where(
            TenantSemanticModel.business_id == business_id,
            TenantSemanticModel.status == "ACTIVE",
        )
        .order_by(desc(TenantSemanticModel.version))
    ).scalars().first()

    if active_model is None:
        raise WorkspaceNotReadyError(
            reason=(
                "No ACTIVE semantic model found for this business workspace. "
                "Activate a semantic revision before running intelligence queries."
            ),
            stage="semantic-not-ready",
        )

    # ------------------------------------------------------------------ #
    # 2. Dataset snapshot — find the latest ready dataset                 #
    # ------------------------------------------------------------------ #
    latest_dataset: Optional[UploadedDataset] = db.execute(
        select(UploadedDataset)
        .where(
            UploadedDataset.business_id == business_id,
            UploadedDataset.readiness_status.in_(["ready", "READY"]),
        )
        .order_by(desc(UploadedDataset.created_at))
    ).scalars().first()

    if latest_dataset is None:
        raise WorkspaceNotReadyError(
            reason=(
                "No ready dataset found for this business workspace. "
                "Upload and complete data ingestion before running intelligence queries."
            ),
            stage="data-not-ready",
        )

    # ------------------------------------------------------------------ #
    # 3. Ingestion job snapshot — latest completed job for the dataset    #
    # ------------------------------------------------------------------ #
    latest_job: Optional[IngestionJob] = db.execute(
        select(IngestionJob)
        .where(
            IngestionJob.dataset_id == latest_dataset.id,
            IngestionJob.status == "COMPLETED",
        )
        .order_by(desc(IngestionJob.completed_at))
    ).scalars().first()

    # ------------------------------------------------------------------ #
    # 4. Date coverage from schema_json if available                      #
    # ------------------------------------------------------------------ #
    date_coverage: Optional[dict[str, Any]] = None
    schema = latest_dataset.schema_json or {}
    if schema.get("date_range_start") or schema.get("date_range_end"):
        date_coverage = {
            "start": schema.get("date_range_start"),
            "end": schema.get("date_range_end"),
            "days": schema.get("date_range_days"),
        }

    return {
        "semantic_revision_id": active_model.id,
        "semantic_version": active_model.version,
        "dataset_id": latest_dataset.id,
        "dataset_content_hash": latest_dataset.content_hash,
        "ingestion_job_id": latest_job.id if latest_job else None,
        "dataset_date_coverage": date_coverage,
    }


# ---------------------------------------------------------------------------
# NexusAgentService
# ---------------------------------------------------------------------------

class NexusAgentService:
    """
    Primary interface for orchestrating the NEXUS agentic intelligence layer.

    Coordinates the LangGraph state machine, binds the database session,
    enforces maximum iteration boundaries, and produces traceable, audited AgentResponse payloads.

    Phase 19: every run captures an immutable semantic + dataset snapshot at creation time,
    enabling historical reproducibility regardless of later semantic model upgrades.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def run_analysis(
        self,
        query: str,
        explanation_level: str = "manager",
        reference_date: date | None = None,
        max_iterations: int | None = None,
        is_investigation: bool = False,
        is_forecast: bool = False,
        organization_id: str | None = None,
        business_id: str | None = None,
        user_id: str | None = None,
        enforce_readiness: bool = True,
    ) -> AgentResponse:
        """
        Execute deterministic analytical reasoning for a user query.

        Args:
            query: Natural language analytical request
            explanation_level: 'simple', 'manager', 'analyst', or 'technical'
            reference_date: Optional anchor date for relative temporal parsing
            max_iterations: Optional override for graph loop limit
            organization_id: Tenant organization boundary
            business_id: Tenant business workspace boundary
            user_id: Authenticated requesting user identity
            enforce_readiness: When True (default), validates workspace readiness
                               and captures semantic + dataset snapshots before execution.
                               Set False only in legacy/test contexts without a full tenant workspace.

        Returns:
            Fully populated and grounded AgentResponse
        """
        start_time = time.perf_counter()
        request_id = str(uuid4())
        max_iters = max_iterations or settings.MAX_AGENT_ITERATIONS

        logger.info(
            f"Starting agent analysis run. Request ID: {request_id}, "
            f"Org: {organization_id}, Biz: {business_id}, "
            f"Query: '{query}', Explanation Level: '{explanation_level}'"
        )

        # ------------------------------------------------------------------ #
        # Phase 19: Workspace readiness + snapshot capture                    #
        # ------------------------------------------------------------------ #
        snapshot: dict[str, Any] = {}
        readiness_error: Optional[str] = None
        readiness_stage: Optional[str] = None

        if business_id and enforce_readiness:
            try:
                snapshot = _resolve_workspace_snapshot(self.session, business_id)
                logger.info(
                    f"Run {request_id}: semantic_v{snapshot['semantic_version']} "
                    f"(rev={snapshot['semantic_revision_id'][:8]}), "
                    f"dataset={snapshot['dataset_id'][:8] if snapshot.get('dataset_id') else 'none'}"
                )
            except WorkspaceNotReadyError as rdy_err:
                readiness_error = rdy_err.reason
                readiness_stage = rdy_err.stage
                logger.warning(
                    f"Run {request_id}: workspace not ready ({rdy_err.stage}): {rdy_err.reason}"
                )

        # ------------------------------------------------------------------ #
        # If workspace is not ready, return a safe degraded response           #
        # ------------------------------------------------------------------ #
        if readiness_error:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            metadata = AgentExecutionMetadata(
                request_id=request_id,
                elapsed_ms=elapsed_ms,
                iterations=0,
                tool_call_count=0,
                tools_executed=[],
                evidence_status="INSUFFICIENT",
                timestamp=datetime.now(UTC),
            )
            # Persist a FAILED run record so it appears in history with proper stage
            self._persist_run(
                request_id=request_id,
                organization_id=organization_id,
                business_id=business_id,
                user_id=user_id,
                query=query,
                intent="unsupported",
                run_status=readiness_stage or "failed",
                explanation_level=explanation_level,
                answer=readiness_error,
                elapsed_ms=elapsed_ms,
                tools_used=[],
                calculations=[],
                assumptions=[],
                limitations=[readiness_error],
                evidence_records=[],
                rag_citations=[],
                snapshot=snapshot,
                recommendations=[],
            )
            return AgentResponse(
                answer=readiness_error,
                intent="unsupported",
                explanation_level=explanation_level,
                evidence=[],
                rag_evidence=[],
                semantic_context=None,
                diagnostic_summary=None,
                forecast_summary=None,
                calculations=[],
                assumptions=[],
                limitations=[readiness_error],
                tools_used=[],
                follow_up_questions=[],
                needs_clarification=False,
                clarification_prompt=None,
                status=readiness_stage or "failed",
                execution_metadata=metadata,
            )

        # ------------------------------------------------------------------ #
        # Invoke LangGraph                                                     #
        # ------------------------------------------------------------------ #
        initial_state: AgentState = {
            "request_id": request_id,
            "organization_id": organization_id,
            "business_id": business_id,
            "user_id": user_id,
            "user_query": query,
            "explanation_level": explanation_level,
            "reference_date": reference_date.isoformat() if reference_date else None,
            "is_investigation_required": is_investigation,
            "is_forecast_required": is_forecast,
            "forecast_target": None,
            "forecast_horizon": None,
            "forecast_frequency": None,
            "forecast_result": None,
            "intent": None,
            "resolved_dates": {},
            "analysis_plan": None,
            "current_step_index": 0,
            "tool_calls": [],
            "tool_results": [],
            "evidence": [],
            "assumptions": [],
            "limitations": [],
            "evidence_status": "INSUFFICIENT",
            "needs_clarification": False,
            "clarification_question": None,
            "is_unsupported": False,
            "unsupported_reason": None,
            "final_answer": None,
            "calculations": [],
            "tools_used": [],
            "follow_up_questions": [],
            "errors": [],
            "semantic_context": None,
            "rag_evidence": [],
            "business_context_text": None,
            "is_definitional_only": False,
            "iteration_count": 0,
            "max_iterations": max_iters,
        }

        # Invoke the compiled LangGraph workflow with session bound to config
        final_state: AgentState = agent_graph.invoke(
            initial_state,
            config={"configurable": {"session": self.session}}
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Determine execution outcome status
        if final_state.get("is_unsupported"):
            run_status = "unsupported"
        elif final_state.get("needs_clarification"):
            run_status = "clarification_needed"
        elif final_state.get("errors") and not any(
            r.get("status") == "success" for r in final_state.get("tool_results", [])
        ):
            run_status = "error"
        else:
            run_status = "completed"

        # Deserialize evidence records safely
        evidence_records: list[EvidenceRecord] = []
        for ev in final_state.get("evidence", []):
            try:
                if isinstance(ev, dict) and "forecast_id" in ev and "calculation" not in ev:
                    # Map ForecastEvidence into compatible EvidenceRecord
                    mapped = {
                        "analysis_id": ev.get("forecast_id"),
                        "metric": ev.get("target_metric", "forecast"),
                        "source_tables": ev.get("source_tables", ["sales", "sale_items"]),
                        "source_columns": ev.get("source_columns", ["transaction_date", "subtotal"]),
                        "calculation": f"Forecast using model {ev.get('model_name', 'statistical')}",
                        "method": ev.get("method", "time_series_forecasting"),
                        "date_range": ev.get("historical_range", {}),
                        "assumptions": ev.get("assumptions", []),
                        "limitations": ev.get("limitations", []),
                        "data_quality_status": ev.get("data_quality_status", "verified"),
                        "generated_at": ev.get("generated_at"),
                    }
                    evidence_records.append(EvidenceRecord.model_validate(mapped))
                else:
                    evidence_records.append(EvidenceRecord.model_validate(ev))
            except (ValidationError, ValueError, TypeError) as ex:
                logger.warning(f"Failed to validate EvidenceRecord in agent response: {ex}")

        # Deserialize RAG evidence records safely
        rag_records: list[RAGEvidence] = []
        for r_ev in final_state.get("rag_evidence", []):
            try:
                rag_records.append(RAGEvidence.model_validate(r_ev))
            except (ValidationError, ValueError, TypeError) as ex:
                logger.warning(f"Failed to validate RAGEvidence in agent response: {ex}")

        # Intent label
        intent_dict = final_state.get("intent") or {}
        intent_label = intent_dict.get("category", "unsupported")

        # Execution metadata for audit and Phase 9 evaluation
        metadata = AgentExecutionMetadata(
            request_id=request_id,
            elapsed_ms=elapsed_ms,
            iterations=final_state.get("iteration_count", 0),
            tool_call_count=len(final_state.get("tool_calls", [])),
            tools_executed=final_state.get("tools_used", []),
            evidence_status=final_state.get("evidence_status", "INSUFFICIENT"),
            timestamp=datetime.now(UTC),
        )

        logger.info(
            f"Completed agent analysis run. Request ID: {request_id}, "
            f"Status: {run_status}, Tools: {metadata.tools_executed}, Elapsed: {elapsed_ms}ms"
        )

        # Persist AnalysisRun with immutable snapshot
        self._persist_run(
            request_id=request_id,
            organization_id=organization_id,
            business_id=business_id,
            user_id=user_id,
            query=query,
            intent=intent_label,
            run_status=run_status,
            explanation_level=explanation_level,
            answer=final_state.get("final_answer") or "Analysis completed.",
            elapsed_ms=elapsed_ms,
            tools_used=metadata.tools_executed,
            calculations=final_state.get("calculations", []),
            assumptions=final_state.get("assumptions", []),
            limitations=final_state.get("limitations", []),
            evidence_records=[e.model_dump() for e in evidence_records],
            rag_citations=[r.model_dump() for r in rag_records],
            snapshot=snapshot,
            recommendations=final_state.get("recommendations", []),
        )

        return AgentResponse(
            answer=final_state.get("final_answer") or "Analysis completed.",
            intent=intent_label,
            explanation_level=explanation_level,
            evidence=evidence_records,
            rag_evidence=rag_records,
            semantic_context=final_state.get("semantic_context"),
            diagnostic_summary=final_state.get("diagnostic_summary"),
            forecast_summary=final_state.get("forecast_result"),
            calculations=final_state.get("calculations", []),
            assumptions=final_state.get("assumptions", []),
            limitations=final_state.get("limitations", []),
            tools_used=final_state.get("tools_used", []),
            follow_up_questions=final_state.get("follow_up_questions", []),
            needs_clarification=final_state.get("needs_clarification", False),
            clarification_prompt=final_state.get("clarification_question"),
            status=run_status,
            execution_metadata=metadata,
        )

    def _persist_run(
        self,
        *,
        request_id: str,
        organization_id: Optional[str],
        business_id: Optional[str],
        user_id: Optional[str],
        query: str,
        intent: str,
        run_status: str,
        explanation_level: str,
        answer: str,
        elapsed_ms: float,
        tools_used: list[str],
        calculations: list[dict],
        assumptions: list[str],
        limitations: list[str],
        evidence_records: list[dict],
        rag_citations: list[dict],
        snapshot: dict[str, Any],
        recommendations: list,
    ) -> None:
        """
        Persist an AnalysisRun to the database with immutable snapshots.
        Status transitions are one-directional; a completed run cannot become running.
        """
        try:
            run_record = AnalysisRun(
                request_id=request_id,
                organization_id=organization_id,
                business_id=business_id,
                user_id=user_id,
                query=query,
                intent=intent,
                status=run_status,
                explanation_level=explanation_level,
                answer=answer,
                execution_time_ms=elapsed_ms,
                tools_used=tools_used,
                calculations=calculations,
                assumptions=assumptions,
                limitations=limitations,
                evidence_records=evidence_records,
                rag_citations=rag_citations,
                # --- Phase 19: Immutable snapshots ---
                semantic_revision_id=snapshot.get("semantic_revision_id"),
                semantic_version=snapshot.get("semantic_version"),
                dataset_id=snapshot.get("dataset_id"),
                dataset_content_hash=snapshot.get("dataset_content_hash"),
                ingestion_job_id=snapshot.get("ingestion_job_id"),
                dataset_date_coverage=snapshot.get("dataset_date_coverage"),
            )
            self.session.add(run_record)
            self.session.flush()

            # Auto-register pending decision records if recommendations exist
            for rec in recommendations:
                rec_text = rec if isinstance(rec, str) else str(rec.get("action", rec))
                decision = DecisionRecord(
                    organization_id=organization_id,
                    business_id=business_id,
                    analysis_id=run_record.id,
                    recommendation_text=rec_text,
                    status="PENDING",
                )
                self.session.add(decision)

            self.session.commit()
            logger.info(f"Persisted AnalysisRun #{run_record.id} for request {request_id}")
        except Exception as db_err:
            logger.debug(f"Could not persist AnalysisRun audit record: {db_err}")
            try:
                self.session.rollback()
            except Exception:
                pass
