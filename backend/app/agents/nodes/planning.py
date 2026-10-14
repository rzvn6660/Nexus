"""Planning and plan validation nodes for the NEXUS agent."""

from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from app.agents.providers.factory import get_llm_provider
from app.agents.state.models import AgentState, IntentCategory
from app.agents.tools.registry import tool_registry


def create_plan_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Formulate a structured, inspectable multi-step analysis plan prior to tool execution.
    Integrates Phase 25D semantic intelligence and Phase 28 Stage 3 historical decision memory:
    respects canonical KPIs, supported dimensions, validated filters, ambiguity, confidence,
    temporal context, tenant context, and historical decision evidence provenance.
    """
    user_query = state["user_query"]
    intent_dict = state.get("intent") or {}
    intent_cat = IntentCategory(intent_dict.get("category", IntentCategory.METRIC_LOOKUP.value))
    resolved_dates = dict(state.get("resolved_dates") or {})
    semantic_context = state.get("semantic_context") or {}

    # 1. Ambiguity Guard: Cannot formulate tool execution for ambiguous terms
    if semantic_context.get("is_ambiguous") or state.get("needs_clarification"):
        clarification_msg = (
            semantic_context.get("clarification_prompt")
            or state.get("clarification_question")
            or "The specified term is ambiguous. Please clarify which metric you would like to analyze."
        )
        return {
            "needs_clarification": True,
            "clarification_question": clarification_msg,
            "evidence_status": "INSUFFICIENT",
            "analysis_plan": None,
            "historical_decisions": [],
            "historical_decision_context": "No previous decision memory records found for this business and context.",
        }

    # 2. Availability & Unsupported Metric Guard: If metric is unsupported or unavailable, explain limitation
    if not semantic_context.get("is_supported", True):
        unsupp_msg = (
            semantic_context.get("unsupported_message")
            or state.get("unsupported_reason")
            or "The requested metric is not currently supported by the NEXUS metric catalog."
        )
        return {
            "is_unsupported": True,
            "unsupported_reason": unsupp_msg,
            "evidence_status": "INSUFFICIENT",
            "analysis_plan": None,
            "historical_decisions": [],
            "historical_decision_context": "No previous decision memory records found for this business and context.",
        }

    avail_status = semantic_context.get("availability_status")
    if avail_status and avail_status in ("REQUIRES_COST_DATA", "INSUFFICIENT_HISTORY", "UNAVAILABLE"):
        unsupp_msg = (
            semantic_context.get("unsupported_message")
            or state.get("unsupported_reason")
            or f"Metric '{semantic_context.get('canonical_name', 'requested metric')}' is {avail_status.lower().replace('_', ' ')} based on tenant records."
        )
        return {
            "is_unsupported": True,
            "unsupported_reason": unsupp_msg,
            "evidence_status": "INSUFFICIENT",
            "analysis_plan": None,
            "historical_decisions": [],
            "historical_decision_context": "No previous decision memory records found for this business and context.",
        }

    # 3. Temporal Context & Fiscal Calendar Preservation
    temporal_ctx = semantic_context.get("temporal_context") or {}
    if temporal_ctx.get("date_from"):
        resolved_dates["date_from"] = str(temporal_ctx["date_from"])
    if temporal_ctx.get("date_to"):
        resolved_dates["date_to"] = str(temporal_ctx["date_to"])
    if temporal_ctx.get("comparison_date_from"):
        resolved_dates["comparison_date_from"] = str(temporal_ctx["comparison_date_from"])
    if temporal_ctx.get("comparison_date_to"):
        resolved_dates["comparison_date_to"] = str(temporal_ctx["comparison_date_to"])
    if temporal_ctx.get("granularity"):
        resolved_dates["granularity"] = str(temporal_ctx["granularity"])
    if temporal_ctx.get("fiscal_calendar"):
        resolved_dates["fiscal_calendar"] = dict(temporal_ctx["fiscal_calendar"])

    # 4. Collect explicit warnings for unsupported dimensions and filters
    warnings: list[str] = []
    limitations: list[str] = list(state.get("limitations") or [])

    unsupp_dims = semantic_context.get("unsupported_dimensions") or []
    for d in unsupp_dims:
        w = f"Dimension '{d}' is not supported for metric '{semantic_context.get('canonical_name', 'requested metric')}' and was omitted from plan."
        warnings.append(w)
        limitations.append(w)

    unsupp_filters = semantic_context.get("unsupported_filters") or {}
    for f_k, f_v in unsupp_filters.items():
        w = f"Filter '{f_k}={f_v}' is not supported for metric '{semantic_context.get('canonical_name', 'requested metric')}' and was omitted from plan."
        warnings.append(w)
        limitations.append(w)

    if semantic_context.get("unsupported_message") and semantic_context["unsupported_message"] not in limitations:
        limitations.append(semantic_context["unsupported_message"])

    # 4.5. Phase 28 Stage 3: Retrieve historical decision memory context
    historical_decisions: list[dict[str, Any]] = []
    historical_context_summary = "No previous decision memory records found for this business and context."

    if state.get("historical_decisions") is not None:
        historical_decisions = list(state.get("historical_decisions") or [])
        historical_context_summary = (
            state.get("historical_decision_context")
            or ("No previous decision memory records found for this business and context." if not historical_decisions else "")
        )
    else:
        # Check if database session is available via LangGraph config or state
        session = None
        if config:
            configurable = config.get("configurable", {})
            session = configurable.get("session")
        if session is None:
            session = state.get("db_session") or state.get("session")

        biz_id = state.get("business_id")
        if session and biz_id:
            try:
                from app.analytics.outcome.schemas import DecisionRetrievalFilter
                from app.analytics.outcome.service import DecisionMemoryService
                from app.models.tenant import UserIdentity

                user_id = state.get("user_id")
                current_user = session.get(UserIdentity, user_id) if user_id else None

                if current_user:
                    target_metric = semantic_context.get("canonical_name")
                    extracted_filters = semantic_context.get("extracted_filters") or {}
                    target_id = extracted_filters.get("sku") or extracted_filters.get("product_id")

                    hist_query = DecisionRetrievalFilter(
                        metric_name=target_metric,
                        action_target_id=target_id,
                        limit=5,
                    )
                    hist_res = DecisionMemoryService.retrieve_historical_decisions(
                        db=session,
                        current_user=current_user,
                        business_id=biz_id,
                        query=hist_query,
                    )
                    historical_decisions = [item.model_dump() for item in hist_res.items]
                    historical_context_summary = hist_res.context_summary
            except Exception:  # noqa: BLE001 - defensive fallback to ensure planning continues safely
                historical_decisions = []
                historical_context_summary = "No previous decision memory records found for this business and context."

    if not historical_context_summary:
        historical_context_summary = "No previous decision memory records found for this business and context."

    if historical_decisions:
        hist_limit_notice = "Historical decision context is observational only; deterministic calculations remain authoritative."
        if hist_limit_notice not in limitations:
            limitations.append(hist_limit_notice)

    # Attach historical decision context to semantic_context for planner/LLM prompt
    semantic_context["historical_decision_context"] = historical_context_summary
    semantic_context["has_historical_decisions"] = bool(historical_decisions)

    # 5. Formulate structured plan via provider
    available_tools = tool_registry.list_tools()
    provider = get_llm_provider()

    # Supply business context to semantic context if available
    if state.get("business_context_text") and "business_context" not in semantic_context:
        semantic_context["business_context"] = state["business_context_text"]

    plan = provider.create_plan(
        query=user_query,
        intent=intent_cat,
        available_tools=available_tools,
        resolved_dates=resolved_dates,
        semantic_context=semantic_context,
    )

    # 6. Ensure unsupported filters and dimensions are not passed to tool arguments
    if unsupp_filters:
        for step in plan.steps:
            for bad_key in unsupp_filters:
                if bad_key in step.arguments:
                    del step.arguments[bad_key]
    if unsupp_dims:
        for step in plan.steps:
            for bad_dim in unsupp_dims:
                if bad_dim in step.arguments:
                    del step.arguments[bad_dim]
                if step.arguments.get("dimension") == bad_dim:
                    del step.arguments["dimension"]

    # 7. Enrich plan with confidence, warnings, semantic context, and provenance
    plan.confidence = float(semantic_context.get("confidence", 1.0))
    plan.warnings = warnings
    plan.semantic_context = semantic_context
    plan.provenance = semantic_context.get("evidence_provenance")
    if "fiscal_calendar" in resolved_dates:
        plan.context_dates["fiscal_calendar"] = resolved_dates["fiscal_calendar"]

    return {
        "analysis_plan": plan.model_dump(),
        "resolved_dates": resolved_dates,
        "limitations": limitations,
        "current_step_index": 0,
        "iteration_count": state.get("iteration_count", 0),
        "historical_decisions": historical_decisions,
        "historical_decision_context": historical_context_summary,
        "is_fallback": getattr(plan, "is_fallback", False),
        "fallback_reason": getattr(plan, "fallback_reason", None),
        "llm_provider_name": getattr(plan, "llm_provider", None) or getattr(provider, "provider_name", "MockLLMProvider"),
        "llm_model_name": getattr(plan, "llm_model", None) or getattr(provider, "model_name", None),
    }



def validate_plan_node(state: AgentState) -> dict[str, Any]:
    """
    Strictly validate that all proposed analytical steps exist in the deterministic
    tool registry, satisfy their Pydantic argument schemas, and do not contain stripped
    unsupported filters, unsupported dimensions, or operate on unverified ambiguous metrics.
    """
    plan_dict = state.get("analysis_plan") or {}
    steps = plan_dict.get("steps", [])
    errors: list[str] = list(state.get("errors", []))
    semantic_context = state.get("semantic_context") or {}

    # Guard against ambiguous execution
    if semantic_context.get("is_ambiguous") or state.get("needs_clarification"):
        errors.append("Plan validation failed: Cannot execute plan for ambiguous query.")
        return {"errors": errors, "evidence_status": "ERROR"}

    # Guard against unavailable metric execution
    if semantic_context.get("availability_status") and semantic_context.get("availability_status") != "AVAILABLE":
        errors.append(
            f"Plan validation failed: Metric '{semantic_context.get('canonical_name')}' "
            f"is unavailable ({semantic_context.get('availability_status')})."
        )
        return {"errors": errors, "evidence_status": "ERROR"}

    # Guard against unsupported metric execution
    if not semantic_context.get("is_supported", True) or state.get("is_unsupported"):
        errors.append("Plan validation failed: Cannot execute plan for unsupported metric.")
        return {"errors": errors, "evidence_status": "ERROR"}

    if not steps:
        errors.append("Analysis plan contains zero steps.")
        return {"errors": errors, "evidence_status": "ERROR"}

    unsupp_filters = semantic_context.get("unsupported_filters") or {}
    unsupp_dims = semantic_context.get("unsupported_dimensions") or []

    for step in steps:
        tool_name = step.get("tool_name")
        args = step.get("arguments", {})

        if not tool_registry.has_tool(tool_name):
            errors.append(f"Security/Validation check failed: Tool '{tool_name}' is not in registry.")
            return {"errors": errors, "evidence_status": "ERROR"}

        # Validate that no stripped unsupported filter leaked into tool arguments
        for bad_key in unsupp_filters:
            if bad_key in args:
                errors.append(
                    f"Plan validation failed: Tool '{tool_name}' argument contains unsupported filter '{bad_key}'."
                )
                return {"errors": errors, "evidence_status": "ERROR"}

        # Validate that no unsupported dimension leaked into tool arguments
        for bad_dim in unsupp_dims:
            if bad_dim in args:
                errors.append(
                    f"Plan validation failed: Tool '{tool_name}' argument contains unsupported dimension '{bad_dim}'."
                )
                return {"errors": errors, "evidence_status": "ERROR"}
            if args.get("dimension") == bad_dim:
                errors.append(
                    f"Plan validation failed: Tool '{tool_name}' dimension argument contains unsupported dimension '{bad_dim}'."
                )
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
