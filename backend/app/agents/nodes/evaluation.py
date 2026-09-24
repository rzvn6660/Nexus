"""Result inspection and evidence sufficiency evaluation nodes."""

from typing import Any

from app.agents.state.models import AgentState, EvidenceSufficiencyStatus


def inspect_result_node(state: AgentState) -> dict[str, Any]:
    """
    Inspect latest tool result output, extracting key metrics and auditing metadata.
    """
    tool_results = state.get("tool_results", [])
    if not tool_results:
        return {
            "evidence_status": EvidenceSufficiencyStatus.INSUFFICIENT.value,
        }

    latest = tool_results[-1]
    if latest.get("status") == "error":
        errors = list(state.get("errors", []))
        err_msg = latest.get("error_message") or "Unknown error in tool execution"
        if err_msg not in errors:
            errors.append(err_msg)
        return {
            "errors": errors,
            "evidence_status": EvidenceSufficiencyStatus.ERROR.value,
        }

    return {}


def check_evidence_node(state: AgentState) -> dict[str, Any]:
    """
    Determine whether collected evidence is sufficient to address the user's analytical query,
    or whether the graph must transition to execute the next step in the analysis plan.
    """
    plan_dict = state.get("analysis_plan") or {}
    steps = plan_dict.get("steps", [])
    current_idx = state.get("current_step_index", 0)
    iteration = state.get("iteration_count", 0)
    max_iters = state.get("max_iterations", 5)
    tool_results = state.get("tool_results", [])
    errors = state.get("errors", [])

    # If critical errors occurred and no results exist
    if errors and not tool_results:
        return {
            "evidence_status": EvidenceSufficiencyStatus.ERROR.value,
        }

    # If more plan steps exist and we haven't hit iteration limit
    next_idx = current_idx + 1
    if next_idx < len(steps) and iteration < max_iters:
        return {
            "current_step_index": next_idx,
            "evidence_status": EvidenceSufficiencyStatus.PARTIAL.value,
        }

    # If all planned steps have executed and we have tool results
    if tool_results:
        has_valid_result = any(r.get("status") == "success" for r in tool_results)
        if has_valid_result:
            return {
                "evidence_status": EvidenceSufficiencyStatus.SUFFICIENT.value,
            }
        else:
            return {
                "evidence_status": EvidenceSufficiencyStatus.ERROR.value,
            }

    return {
        "evidence_status": EvidenceSufficiencyStatus.INSUFFICIENT.value,
    }
