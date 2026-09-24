"""Stateful LangGraph workflow definition for the NEXUS analytical agent."""

from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.agents.nodes.evaluation import check_evidence_node, inspect_result_node
from app.agents.nodes.execution import execute_tool_node
from app.agents.nodes.explanation import generate_explanation_node
from app.agents.nodes.planning import create_plan_node, validate_plan_node
from app.agents.nodes.specialized import handle_clarification_node, handle_unsupported_node
from app.agents.nodes.understand import understand_request_node
from app.agents.state.models import AgentState, EvidenceSufficiencyStatus


def route_after_understanding(
    state: AgentState
) -> Literal["handle_unsupported", "handle_clarification", "create_plan"]:
    """Branch immediately if request is unsupported or ambiguous."""
    if state.get("is_unsupported"):
        return "handle_unsupported"
    if state.get("needs_clarification"):
        return "handle_clarification"
    return "create_plan"


def route_after_plan_validation(
    state: AgentState
) -> Literal["execute_tool", "generate_explanation"]:
    """Proceed to tool execution if plan is valid, otherwise report validation failure."""
    if state.get("evidence_status") == "ERROR" or (state.get("errors") and not state.get("tool_results")):
        return "generate_explanation"
    return "execute_tool"


def route_after_evidence_check(
    state: AgentState
) -> Literal["execute_tool", "generate_explanation"]:
    """Decide whether to execute another tool in the plan or finish and generate explanation."""
    status = state.get("evidence_status")
    iteration = state.get("iteration_count", 0)
    max_iters = state.get("max_iterations", 5)

    if status == EvidenceSufficiencyStatus.PARTIAL.value and iteration < max_iters:
        return "execute_tool"
    return "generate_explanation"


def build_agent_graph() -> StateGraph:
    """
    Construct the stateful LangGraph analytical orchestration graph.
    
    Workflow Topology:
    START
      ↓
    understand_request
      ├── [is_unsupported] ──────────→ handle_unsupported ──→ END
      ├── [needs_clarification] ─────→ handle_clarification ─→ END
      └── [valid] ───────────────────→ create_plan
                                            ↓
                                       validate_plan
                                            ↓
                                       [is_valid?]
                                       ├── [no] ──→ generate_explanation ──→ END
                                       └── [yes] ─→ execute_tool
                                                        ↓
                                                   inspect_result
                                                        ↓
                                                   check_evidence
                                                        ↓
                                                   [sufficient?]
                                                   ├── [partial] ─→ execute_tool (loop)
                                                   └── [yes/err] ─→ generate_explanation ──→ END
    """
    builder = StateGraph(AgentState)

    # 1. Register Nodes
    builder.add_node("understand_request", understand_request_node)
    builder.add_node("handle_unsupported", handle_unsupported_node)
    builder.add_node("handle_clarification", handle_clarification_node)
    builder.add_node("create_plan", create_plan_node)
    builder.add_node("validate_plan", validate_plan_node)
    builder.add_node("execute_tool", execute_tool_node)
    builder.add_node("inspect_result", inspect_result_node)
    builder.add_node("check_evidence", check_evidence_node)
    builder.add_node("generate_explanation", generate_explanation_node)

    # 2. Wire Edges
    builder.add_edge(START, "understand_request")

    builder.add_conditional_edges(
        "understand_request",
        route_after_understanding,
        {
            "handle_unsupported": "handle_unsupported",
            "handle_clarification": "handle_clarification",
            "create_plan": "create_plan",
        },
    )

    builder.add_edge("handle_unsupported", END)
    builder.add_edge("handle_clarification", END)

    builder.add_edge("create_plan", "validate_plan")

    builder.add_conditional_edges(
        "validate_plan",
        route_after_plan_validation,
        {
            "execute_tool": "execute_tool",
            "generate_explanation": "generate_explanation",
        },
    )

    builder.add_edge("execute_tool", "inspect_result")
    builder.add_edge("inspect_result", "check_evidence")

    builder.add_conditional_edges(
        "check_evidence",
        route_after_evidence_check,
        {
            "execute_tool": "execute_tool",
            "generate_explanation": "generate_explanation",
        },
    )

    builder.add_edge("generate_explanation", END)

    return builder


# Compiled graph singleton
agent_graph = build_agent_graph().compile()
