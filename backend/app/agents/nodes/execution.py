"""Tool execution node for running deterministic AnalyticsService capabilities."""

from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session

from app.agents.state.models import AgentState
from app.agents.tools.registry import tool_registry
from app.core.database import SessionLocal


def execute_tool_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Execute the deterministic tool designated for the current step in the analysis plan.
    Strictly forbids raw SQL, shell execution, or unvalidated parameters.
    """
    iteration = state.get("iteration_count", 0) + 1
    max_iters = state.get("max_iterations", 5)

    if iteration > max_iters:
        errors = list(state.get("errors", []))
        errors.append(f"Maximum iteration limit ({max_iters}) reached.")
        return {
            "iteration_count": iteration,
            "errors": errors,
            "evidence_status": "PARTIAL",
        }

    plan_dict = state.get("analysis_plan") or {}
    steps = plan_dict.get("steps", [])
    step_idx = state.get("current_step_index", 0)

    if step_idx >= len(steps):
        return {
            "iteration_count": iteration,
            "evidence_status": "SUFFICIENT",
        }

    current_step = steps[step_idx]
    tool_name = current_step.get("tool_name")
    arguments = current_step.get("arguments", {})

    # Extract session from LangGraph config or create temporary session
    session_provided = False
    session: Session | None = None
    if config and isinstance(config, dict):
        configurable = config.get("configurable", {})
        session = configurable.get("session")
        if session:
            session_provided = True

    if not session:
        session = SessionLocal()

    tool_calls = list(state.get("tool_calls", []))
    tool_results = list(state.get("tool_results", []))
    evidence_list = list(state.get("evidence", []))
    assumptions_list = list(state.get("assumptions", []))
    limitations_list = list(state.get("limitations", []))
    tools_used = list(state.get("tools_used", []))
    calculations = list(state.get("calculations", []))
    errors = list(state.get("errors", []))

    try:
        # Record call attempt
        tool_calls.append({
            "tool": tool_name,
            "arguments": arguments,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        # Execute registered tool
        exec_result = tool_registry.execute(tool_name, session, arguments)
        tool_results.append(exec_result.model_dump())

        if exec_result.status == "success":
            if tool_name not in tools_used:
                tools_used.append(tool_name)
            if exec_result.evidence:
                evidence_list.append(exec_result.evidence)
            for a in exec_result.assumptions:
                if a not in assumptions_list:
                    assumptions_list.append(a)
            for lim in exec_result.limitations:
                if lim not in limitations_list:
                    limitations_list.append(lim)

            # Record calculation summary
            if exec_result.evidence and exec_result.evidence.get("calculation"):
                calculations.append({
                    "tool": tool_name,
                    "calculation": exec_result.evidence.get("calculation"),
                    "method": exec_result.evidence.get("method"),
                })
        else:
            errors.append(f"Tool '{tool_name}' execution failed: {exec_result.error_message}")

    finally:
        if not session_provided and session:
            session.close()

    return {
        "iteration_count": iteration,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "evidence": evidence_list,
        "assumptions": assumptions_list,
        "limitations": limitations_list,
        "tools_used": tools_used,
        "calculations": calculations,
        "errors": errors,
    }
