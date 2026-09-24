"""Planning and plan validation nodes for the NEXUS agent."""

from typing import Any

from pydantic import ValidationError

from app.agents.providers.factory import get_llm_provider
from app.agents.state.models import AgentState, IntentCategory
from app.agents.tools.registry import tool_registry


def create_plan_node(state: AgentState) -> dict[str, Any]:
    """
    Formulate a structured, inspectable multi-step analysis plan prior to tool execution.
    """
    user_query = state["user_query"]
    intent_dict = state.get("intent") or {}
    intent_cat = IntentCategory(intent_dict.get("category", IntentCategory.METRIC_LOOKUP.value))
    resolved_dates = state.get("resolved_dates") or {}

    available_tools = tool_registry.list_tools()
    provider = get_llm_provider()

    plan = provider.create_plan(
        query=user_query,
        intent=intent_cat,
        available_tools=available_tools,
        resolved_dates=resolved_dates,
    )

    return {
        "analysis_plan": plan.model_dump(),
        "current_step_index": 0,
        "iteration_count": state.get("iteration_count", 0),
    }


def validate_plan_node(state: AgentState) -> dict[str, Any]:
    """
    Strictly validate that all proposed analytical steps exist in the deterministic
    tool registry and satisfy their Pydantic argument schemas.
    """
    plan_dict = state.get("analysis_plan") or {}
    steps = plan_dict.get("steps", [])
    errors: list[str] = list(state.get("errors", []))

    if not steps:
        errors.append("Analysis plan contains zero steps.")
        return {"errors": errors, "evidence_status": "ERROR"}

    for step in steps:
        tool_name = step.get("tool_name")
        args = step.get("arguments", {})

        if not tool_registry.has_tool(tool_name):
            errors.append(f"Security/Validation check failed: Tool '{tool_name}' is not in registry.")
            return {"errors": errors, "evidence_status": "ERROR"}

        tool = tool_registry.get_tool(tool_name)
        if tool:
            try:
                tool.input_schema.model_validate(args)
            except ValidationError as ve:
                errors.append(f"Plan validation failed for tool '{tool_name}': {ve}")
                return {"errors": errors, "evidence_status": "ERROR"}

    return {
        "errors": errors,
    }
