"""NexusAgentService orchestration facade executing stateful LangGraph analytical flows."""

import time
from datetime import UTC, date, datetime
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.graph.workflow import agent_graph
from app.agents.state.models import AgentState
from app.analytics.evidence.models import EvidenceRecord
from app.core.config import settings
from app.core.logging import get_logger
from app.models.history import AnalysisRun, DecisionRecord
from app.rag.retrieval.models import RAGEvidence
from app.schemas.agent import AgentExecutionMetadata, AgentResponse

logger = get_logger(__name__)


class NexusAgentService:
    """
    Primary interface for orchestrating the NEXUS agentic intelligence layer.
    
    Coordinates the LangGraph state machine, binds the database session,
    enforces maximum iteration boundaries, and produces traceable, audited AgentResponse payloads.
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
    ) -> AgentResponse:
        """
        Execute deterministic analytical reasoning for a user query.
        
        Args:
            query: Natural language analytical request
            explanation_level: 'simple', 'manager', 'analyst', or 'technical'
            reference_date: Optional anchor date for relative temporal parsing
            max_iterations: Optional override for graph loop limit
            
        Returns:
            Fully populated and grounded AgentResponse
        """
        start_time = time.perf_counter()
        request_id = str(uuid4())
        max_iters = max_iterations or settings.MAX_AGENT_ITERATIONS

        logger.info(
            f"Starting agent analysis run. Request ID: {request_id}, "
            f"Query: '{query}', Explanation Level: '{explanation_level}'"
        )

        initial_state: AgentState = {
            "request_id": request_id,
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
            status = "unsupported"
        elif final_state.get("needs_clarification"):
            status = "clarification_needed"
        elif final_state.get("errors") and not any(
            r.get("status") == "success" for r in final_state.get("tool_results", [])
        ):
            status = "error"
        else:
            status = "completed"

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
            f"Status: {status}, Tools: {metadata.tools_executed}, Elapsed: {elapsed_ms}ms"
        )

        # Persist audit record in AnalysisRun and DecisionRecord tables
        try:
            run_record = AnalysisRun(
                request_id=request_id,
                query=query,
                intent=intent_label,
                status=status,
                explanation_level=explanation_level,
                answer=final_state.get("final_answer") or "Analysis completed.",
                execution_time_ms=elapsed_ms,
                tools_used=metadata.tools_executed,
                calculations=final_state.get("calculations", []),
                assumptions=final_state.get("assumptions", []),
                limitations=final_state.get("limitations", []),
                evidence_records=[e.model_dump() for e in evidence_records],
                rag_citations=[r.model_dump() for r in rag_records],
            )
            self.session.add(run_record)
            self.session.flush()

            # Auto-register pending decision records if recommendations exist
            recommendations = final_state.get("recommendations", [])
            for rec in recommendations:
                rec_text = rec if isinstance(rec, str) else str(rec.get("action", rec))
                decision = DecisionRecord(
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
            status=status,
            execution_metadata=metadata,
        )
