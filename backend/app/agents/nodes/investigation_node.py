"""LangGraph nodes for executing structured, adaptive diagnostic investigations."""

from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session

from app.agents.state.models import AgentState
from app.agents.tools.registry import tool_registry
from app.core.logging import get_logger
from app.investigation.evidence import EvidenceSynthesizer
from app.investigation.hypotheses import HypothesisEngine
from app.investigation.models import (
    InvestigationHypothesis,
    InvestigationObservation,
    InvestigationPlan,
    InvestigationStep,
)
from app.investigation.planner import InvestigationPlanner
from app.investigation.strategies import get_investigation_strategy

logger = get_logger(__name__)


def create_investigation_plan_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """
    Formulate a structured InvestigationPlan with initial candidate hypotheses
    for diagnostic inquiries.
    """
    query = state["user_query"]
    semantic_context = state.get("semantic_context")
    resolved_dates = state.get("resolved_dates") or {}

    plan, errors = InvestigationPlanner.plan(
        query=query,
        semantic_context=semantic_context,
        resolved_dates=resolved_dates,
    )

    if errors:
        return {
            "errors": errors,
            "evidence_status": "ERROR",
            "is_unsupported": True,
            "unsupported_reason": "Investigation plan validation failed: " + "; ".join(errors),
        }

    strategy = get_investigation_strategy(plan.investigation_type)
    inv_id = f"INV-{state.get('request_id', '0')[:8].upper()}"

    initial_hypotheses = strategy.generate_candidate_hypotheses(
        investigation_id=inv_id,
        resolved_dates=plan.comparison_dates,
    )

    return {
        "investigation_id": inv_id,
        "investigation_goal": plan.goal,
        "investigation_type": plan.investigation_type.value,
        "investigation_plan": plan.model_dump(),
        "investigation_steps": [s.model_dump() for s in plan.steps],
        "current_investigation_step": 0,
        "hypotheses": [h.model_dump() for h in initial_hypotheses],
        "hypothesis_results": [],
        "evidence_items": [],
        "evidence_gaps": [],
        "investigation_status": "in_progress",
        "investigation_iterations": 0,
        "max_investigation_iterations": plan.max_steps,
    }


def execute_investigation_step_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """
    Execute the next scheduled investigative step, extract empirical observations,
    and update candidate hypothesis evaluation.
    """
    session: Session | None = None
    if config and "configurable" in config:
        session = config["configurable"].get("session")

    plan_dict = state.get("investigation_plan") or {}
    plan = InvestigationPlan.model_validate(plan_dict)
    steps_data = list(state.get("investigation_steps", []))
    current_idx = state.get("current_investigation_step", 0)
    hyp_dicts = list(state.get("hypotheses", []))
    hypotheses = [InvestigationHypothesis.model_validate(h) for h in hyp_dicts]
    tool_results = list(state.get("tool_results", []))
    existing_obs = [InvestigationObservation.model_validate(o) for o in state.get("evidence_items", [])]
    existing_evidence = list(state.get("evidence", []))
    tools_used = list(state.get("tools_used", []))
    assumptions = list(state.get("assumptions", []))
    limitations = list(state.get("limitations", []))

    if current_idx >= len(steps_data):
        return {
            "investigation_status": "completed",
        }

    step = InvestigationStep.model_validate(steps_data[current_idx])
    tool = tool_registry.get_tool(step.tool)

    if not tool or not session:
        step.executed = True
        step.result_summary = {"status": "error", "error": "Tool not found or missing session"}
        steps_data[current_idx] = step.model_dump()
        return {
            "investigation_steps": steps_data,
            "current_investigation_step": current_idx + 1,
            "investigation_iterations": state.get("investigation_iterations", 0) + 1,
        }

    exec_result = tool.execute(session, step.arguments)
    step.executed = True
    step.result_summary = {
        "status": exec_result.status,
        "execution_time_ms": exec_result.execution_time_ms,
    }
    steps_data[current_idx] = step.model_dump()
    tools_used.append(step.tool)

    if exec_result.status == "success":
        tool_results.append({
            "step": current_idx + 1,
            "tool": step.tool,
            "result": exec_result.result,
        })
        if exec_result.evidence:
            existing_evidence.append(exec_result.evidence)

        assumptions.extend(exec_result.assumptions)
        limitations.extend(exec_result.limitations)

        # Extract observations
        new_obs = _extract_observations(current_idx + 1, step.tool, exec_result.result, plan)
        all_obs = existing_obs + new_obs

        # Update hypotheses
        evaluated_hyps = HypothesisEngine.evaluate_hypotheses(
            hypotheses=hypotheses,
            tool_results=tool_results,
            observations=all_obs,
        )

        # Check adaptive branching
        strategy = get_investigation_strategy(plan.investigation_type)
        if plan.adaptive_branching_enabled and len(steps_data) < plan.max_steps:
            adaptive_step = strategy.evaluate_adaptive_branch(
                current_step_count=len(steps_data),
                max_steps=plan.max_steps,
                last_step=step,
                last_result=exec_result.result,
                resolved_dates=plan.context_dates,
            )
            if adaptive_step:
                already = any(s["tool"] == adaptive_step.tool and s["arguments"] == adaptive_step.arguments for s in steps_data)
                if not already:
                    adaptive_step.step = len(steps_data) + 1
                    steps_data.append(adaptive_step.model_dump())

        tool_calls = list(state.get("tool_calls", []))
        tool_calls.append({"tool": step.tool, "arguments": step.arguments})

        return {
            "investigation_steps": steps_data,
            "current_investigation_step": current_idx + 1,
            "investigation_iterations": state.get("investigation_iterations", 0) + 1,
            "iteration_count": state.get("iteration_count", 0) + 1,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "evidence": existing_evidence,
            "evidence_items": [o.model_dump() for o in all_obs],
            "hypotheses": [h.model_dump() for h in evaluated_hyps],
            "tools_used": sorted(set(tools_used)),
            "assumptions": sorted(set(assumptions)),
            "limitations": sorted(set(limitations)),
        }

    return {
        "investigation_steps": steps_data,
        "current_investigation_step": current_idx + 1,
        "investigation_iterations": state.get("investigation_iterations", 0) + 1,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "tools_used": sorted(set(tools_used)),
    }


def synthesize_investigation_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """
    Synthesize tested hypotheses into audited diagnostic conclusions and generate
    the grounded diagnostic narrative.
    """
    plan_dict = state.get("investigation_plan") or {}
    plan = InvestigationPlan.model_validate(plan_dict)

    obs = [InvestigationObservation.model_validate(o) for o in state.get("evidence_items", [])]
    hyps = [InvestigationHypothesis.model_validate(h) for h in state.get("hypotheses", [])]
    tools_used = state.get("tools_used", [])
    tool_results = state.get("tool_results", [])
    rag_context_text = state.get("business_context_text")

    strategy = get_investigation_strategy(plan.investigation_type)
    evidence_gaps = strategy.identify_evidence_gaps(tools_used, tool_results)

    conclusions = EvidenceSynthesizer.synthesize_conclusions(hyps, obs)

    explanation = EvidenceSynthesizer.generate_explanation(
        plan=plan,
        observations=obs,
        hypotheses=hyps,
        conclusions=conclusions,
        evidence_gaps=evidence_gaps,
        rag_context_text=rag_context_text,
    )

    exp_lvl = state.get("explanation_level", "manager")
    if exp_lvl in ("analyst", "technical"):
        existing_evidence = state.get("evidence", [])
        if existing_evidence and "Traceability & Evidence" not in explanation:
            explanation += "\n\n--- Traceability & Evidence ---"
            for ev in existing_evidence:
                explanation += f"\n• Metric: {ev.get('metric')}"
                explanation += f"\n  Source tables: {', '.join(ev.get('source_tables', []))}"
                explanation += f"\n  Formula/Rule: {ev.get('calculation')}"
                if ev.get("limitations"):
                    explanation += f"\n  Limitations: {'; '.join(ev.get('limitations', []))}"

    top_summary = conclusions[0].statement if conclusions else "Investigation concluded with collected metrics."
    diagnostic_summary = {
        "investigation_type": plan.investigation_type.value,
        "conclusions_count": len(conclusions),
        "primary_conclusion": top_summary,
    }

    return {
        "final_answer": explanation,
        "evidence_gaps": [g.model_dump() for g in evidence_gaps],
        "diagnostic_summary": diagnostic_summary,
        "investigation_status": "completed",
        "evidence_status": "SUFFICIENT",
        "follow_up_questions": [
            "Would you like to drill into product-level margins for the top contributing categories?",
            "Should we analyze customer cohort retention over a multi-month period?",
        ],
    }


def _extract_observations(
    step_num: int,
    tool_name: str,
    result: dict[str, Any],
    plan: InvestigationPlan,
) -> list[InvestigationObservation]:
    """Extract factual observations from step output."""
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
