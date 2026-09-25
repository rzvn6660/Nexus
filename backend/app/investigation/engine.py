"""Investigation Engine orchestration service coordinating diagnostic analysis."""

import time
from datetime import date
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agents.tools.date_interpreter import DateInterpreter
from app.agents.tools.registry import tool_registry
from app.analytics.evidence.models import EvidenceRecord
from app.core.logging import get_logger
from app.investigation.evidence import EvidenceSynthesizer
from app.investigation.hypotheses import HypothesisEngine
from app.investigation.models import (
    InvestigationObservation,
    InvestigationPlan,
    InvestigationStep,
    StoppedReason,
)
from app.investigation.planner import InvestigationPlanner
from app.investigation.schemas import InvestigationResponse
from app.investigation.strategies import get_investigation_strategy
from app.rag.retrieval.models import RAGEvidence
from app.rag.retrieval.retriever import HybridRetriever
from app.rag.semantic.ontology import semantic_resolver

logger = get_logger(__name__)


class InvestigationEngine:
    """
    Primary orchestrator for multi-step, adaptive diagnostic business investigations.
    
    Coordinates the entire investigation lifecycle:
    1. Semantic grounding & temporal boundary resolution
    2. Structured, bounded investigation planning
    3. RAG business context and policy retrieval
    4. Deterministic analytics tool execution
    5. Factual observation extraction
    6. Candidate hypothesis testing and status updating
    7. Adaptive drill-down branching
    8. Evidence gap auditing
    9. Causality-safeguarded conclusion synthesis
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.retriever = HybridRetriever(session)
        self.semantic_resolver = semantic_resolver

    def investigate(
        self,
        query: str,
        explanation_level: str = "manager",
        reference_date: date | None = None,
    ) -> InvestigationResponse:
        """Execute a full diagnostic investigation answering 'Why did this change occur?'."""
        start_time = time.perf_counter()
        investigation_id = f"INV-{uuid4().hex[:8].upper()}"

        logger.info(f"Starting investigation {investigation_id} for query: '{query}'")

        # 1. Temporal boundary interpretation
        resolved_dates = DateInterpreter.interpret(query, reference_date=reference_date)

        # 2. Semantic layer resolution
        semantic_res = self.semantic_resolver.resolve(query)
        if semantic_res.is_ambiguous:
            logger.info(f"Investigation {investigation_id} requires clarification: {semantic_res.clarification_prompt}")
            candidates = [k.display_name for k in semantic_res.candidate_kpis]
            return InvestigationResponse(
                status="clarification_needed",
                question=query,
                summary="Business terminology in inquiry requires clarification.",
                investigation_type="unresolved",
                explanation=semantic_res.clarification_prompt or "Please clarify ambiguous terminology.",
                stopped_reason="terminology_ambiguity",
                follow_up_questions=candidates,
            )

        if not semantic_res.is_supported:
            return InvestigationResponse(
                status="unsupported",
                question=query,
                summary="Inquiry references unsupported metrics or capabilities.",
                investigation_type="unsupported",
                explanation=semantic_res.unsupported_message or "Metric not currently supported.",
                stopped_reason="unsupported_metric",
            )

        semantic_context = None
        if semantic_res.resolved_kpi:
            semantic_context = semantic_res.resolved_kpi.model_dump()

        # 3. Formulate Investigation Plan
        plan, plan_errors = InvestigationPlanner.plan(
            query=query,
            semantic_context=semantic_context,
            resolved_dates=resolved_dates,
        )

        if plan_errors:
            logger.error(f"Plan validation errors for {investigation_id}: {plan_errors}")
            return InvestigationResponse(
                status="failed",
                question=query,
                summary="Investigation plan failed security/validation checks.",
                investigation_type=plan.investigation_type.value,
                explanation="Investigation halted due to plan validation failure: " + "; ".join(plan_errors),
                stopped_reason="plan_validation_failed",
            )

        strategy = get_investigation_strategy(plan.investigation_type)

        # 4. Retrieve Business Context RAG
        rag_evidence: list[RAGEvidence] = []
        rag_context_text: str | None = None
        try:
            rag_result = self.retriever.retrieve(
                query=f"{query} {plan.investigation_type.value}",
                top_k=2,
            )
            rag_evidence = rag_result.evidence
            rag_context_text = rag_result.context_text
        except Exception as e:  # noqa: BLE001
            logger.warning(f"RAG retrieval skipped in investigation {investigation_id}: {e}")

        # 5. Formulate Candidate Hypotheses
        hypotheses = strategy.generate_candidate_hypotheses(
            investigation_id=investigation_id,
            resolved_dates=plan.comparison_dates,
        )

        # 6. Execute Investigative Steps Loop
        executed_steps: list[InvestigationStep] = []
        tools_used: list[str] = []
        tool_results: list[dict[str, Any]] = []
        evidence_records: list[EvidenceRecord] = []
        observations: list[InvestigationObservation] = []
        assumptions: list[str] = [
            "Baseline and comparison intervals are evaluated using transaction recording dates.",
            "All financial metrics are evaluated deterministically through Phase 3 GAAP-aligned models.",
        ]
        limitations: list[str] = [
            "Transactional data measures internal commercial operations only; external competitive factors are unobserved.",
        ]
        stopped_reason = StoppedReason.SUFFICIENT_EVIDENCE

        # Queue of steps to execute (starts with initial plan steps)
        step_queue = list(plan.steps)
        current_step_num = 1

        while step_queue:
            if len(executed_steps) >= plan.max_steps:
                stopped_reason = StoppedReason.ITERATION_LIMIT_REACHED
                logger.info(f"Investigation {investigation_id} reached max steps limit ({plan.max_steps}).")
                break

            current_step = step_queue.pop(0)
            current_step.step = current_step_num

            # Execute tool safely via registry
            tool = tool_registry.get_tool(current_step.tool)
            if not tool:
                logger.warning(f"Tool '{current_step.tool}' not found during investigation step.")
                continue

            tool_exec_result = tool.execute(self.session, current_step.arguments)
            current_step.executed = True
            current_step.result_summary = {
                "status": tool_exec_result.status,
                "execution_time_ms": tool_exec_result.execution_time_ms,
            }

            executed_steps.append(current_step)
            tools_used.append(current_step.tool)

            if tool_exec_result.status == "success":
                tool_results.append({
                    "step": current_step_num,
                    "tool": current_step.tool,
                    "result": tool_exec_result.result,
                })

                if tool_exec_result.evidence:
                    try:
                        evidence_records.append(EvidenceRecord.model_validate(tool_exec_result.evidence))
                    except Exception:  # noqa: BLE001, S110
                        pass

                assumptions.extend(tool_exec_result.assumptions)
                limitations.extend(tool_exec_result.limitations)

                # Extract empirical observations from results
                cls_obs = self._extract_observations(
                    current_step_num, current_step.tool, tool_exec_result.result, plan
                )
                observations.extend(cls_obs)

                # Evaluate / update candidate hypotheses
                hypotheses = HypothesisEngine.evaluate_hypotheses(
                    hypotheses=hypotheses,
                    tool_results=tool_results,
                    observations=observations,
                )

                # Evaluate adaptive branching if enabled
                if plan.adaptive_branching_enabled and len(executed_steps) < plan.max_steps:
                    adaptive_step = strategy.evaluate_adaptive_branch(
                        current_step_count=len(executed_steps),
                        max_steps=plan.max_steps,
                        last_step=current_step,
                        last_result=tool_exec_result.result,
                        resolved_dates=plan.context_dates,
                    )
                    if adaptive_step:
                        # Ensure not duplicate of already queued/executed tool
                        already_done = any(s.tool == adaptive_step.tool and s.arguments == adaptive_step.arguments for s in executed_steps)
                        if not already_done:
                            logger.info(f"Investigation {investigation_id} dynamically branched step: {adaptive_step.purpose}")
                            step_queue.append(adaptive_step)

            else:
                logger.warning(f"Step {current_step_num} ({current_step.tool}) failed: {tool_exec_result.error_message}")

            current_step_num += 1

        # 7. Identify Evidence Gaps
        evidence_gaps = strategy.identify_evidence_gaps(tools_used, tool_results)

        # 8. Synthesize Conclusions & Grounded Explanation
        conclusions = EvidenceSynthesizer.synthesize_conclusions(
            hypotheses=hypotheses,
            observations=observations,
        )

        explanation = EvidenceSynthesizer.generate_explanation(
            plan=plan,
            observations=observations,
            hypotheses=hypotheses,
            conclusions=conclusions,
            evidence_gaps=evidence_gaps,
            rag_context_text=rag_context_text,
        )

        # Summary formation
        top_conclusion = conclusions[0].statement if conclusions else "Investigation completed; empirical metrics collected."
        summary = f"Diagnostic investigation for '{query}' completed in {len(executed_steps)} steps. {top_conclusion}"

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(f"Investigation {investigation_id} completed in {elapsed_ms}ms with {len(conclusions)} conclusions.")

        # De-duplicate tools used, assumptions, and limitations
        clean_tools_used = sorted(set(tools_used))
        clean_assumptions = sorted(set(assumptions))
        clean_limitations = sorted(set(limitations))

        return InvestigationResponse(
            status="completed",
            question=query,
            summary=summary,
            investigation_type=plan.investigation_type.value,
            observations=observations,
            hypotheses=hypotheses,
            conclusions=conclusions,
            evidence=evidence_records,
            rag_evidence=rag_evidence,
            evidence_gaps=evidence_gaps,
            assumptions=clean_assumptions,
            limitations=clean_limitations,
            tools_used=clean_tools_used,
            investigation_steps=executed_steps,
            stopped_reason=stopped_reason.value,
            follow_up_questions=[
                "Would you like to drill into product-level margins for the top contributing categories?",
                "Should we analyze customer cohort retention over a multi-month period?",
            ],
            explanation=explanation,
        )

    def _extract_observations(
        self,
        step_num: int,
        tool_name: str,
        result: dict[str, Any],
        plan: InvestigationPlan,
    ) -> list[InvestigationObservation]:
        """Convert deterministic tool output primitives into empirical observation objects."""
        obs: list[InvestigationObservation] = []

        if tool_name == "get_financial_summary":
            net_sales = result.get("net_sales", {})
            curr_val = float(net_sales.get("value", 0.0))
            comp_val = float(net_sales.get("comparison_value") or 0.0) if net_sales.get("comparison_value") is not None else None
            change_pct = float(net_sales.get("percentage_change") or 0.0) if net_sales.get("percentage_change") is not None else None

            chg_str = f"{change_pct:+.1f}%" if change_pct is not None else ""
            statement = f"Net Sales (Revenue) was measured at ${curr_val:,.2f}"
            if comp_val is not None:
                statement += f" compared to ${comp_val:,.2f} in the baseline comparison period ({chg_str})."
            else:
                statement += "."

            obs.append(
                InvestigationObservation(
                    id=f"OBS-{step_num}-FIN",
                    statement=statement,
                    metric="net_sales",
                    value_baseline=comp_val,
                    value_current=curr_val,
                    change_pct=change_pct,
                    period_baseline=str(plan.baseline_dates.get("date_from")),
                    period_current=str(plan.comparison_dates.get("date_from")),
                )
            )

        elif tool_name == "run_variance_analysis":
            dimension = result.get("dimension", "dimension")
            items = (
                result.get("top_negative_contributors", [])
                or result.get("top_positive_contributors", [])
                or result.get("items", [])
            )
            total_var = float(result.get("total_variance", 0.0))
            if items:
                top = items[0]
                name = top.get("entity_name") or top.get("entity_id", "Unknown")
                share = abs(float(top.get("contribution_to_change_pct", top.get("contribution_percentage", 0.0))))
                statement = (
                    f"Variance analysis by {dimension} identified '{name}' as the largest contributor, "
                    f"accounting for {share:.1f}% of total measured variance (${total_var:,.2f})."
                )
                obs.append(
                    InvestigationObservation(
                        id=f"OBS-{step_num}-VAR-{dimension.upper()}",
                        statement=statement,
                        metric=f"variance_{dimension}",
                        value_current=total_var,
                    )
                )

        elif tool_name == "run_price_volume_mix":
            vol = float(result.get("volume_effect", 0.0))
            price = float(result.get("price_effect", 0.0))
            mix = float(result.get("mix_effect", 0.0))
            total = float(result.get("total_variance", 1.0))
            statement = (
                f"Price/Volume/Mix decomposition reconciled revenue variance into: "
                f"Volume Effect = ${vol:,.2f}, Price Effect = ${price:,.2f}, Mix Effect = ${mix:,.2f}."
            )
            obs.append(
                InvestigationObservation(
                    id=f"OBS-{step_num}-PVM",
                    statement=statement,
                    metric="price_volume_mix",
                    value_current=total,
                )
            )

        return obs
