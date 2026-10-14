"""Explanation synthesis node generating grounded, non-hallucinated analytical narratives."""

from typing import Any

from app.agents.providers.factory import get_llm_provider
from app.agents.state.models import AgentState, AnalysisPlan, ExplanationLevel
from app.investigation.validators import CausalitySafeguard


def generate_explanation_node(state: AgentState) -> dict[str, Any]:
    """
    Synthesize natural language explanation grounded strictly in the executed tools and evidence.
    Generates intelligent follow-up suggestions for analyst and business user workflows.
    """
    user_query = state.get("user_query", "")
    errors = state.get("errors", [])
    tool_results = state.get("tool_results", [])
    evidence = state.get("evidence", [])
    business_context = state.get("business_context_text")
    is_definitional = state.get("is_definitional_only", False)

    # If critical errors occurred and no tools succeeded AND this is not a definitional question
    if errors and not is_definitional and not any(r.get("status") == "success" for r in tool_results):
        err_text = "\n".join(errors)
        return {
            "final_answer": (
                "I was unable to complete the requested analysis due to the following issue(s):\n"
                f"{err_text}\n\n"
                "Please verify the requested timeframe, metrics, and parameters."
            ),
            "follow_up_questions": [
                "Would you like to try a different date range?",
                "Would you like an overview of overall business summary metrics instead?",
            ],
        }

    exp_lvl_str = state.get("explanation_level", "manager")
    try:
        exp_lvl = ExplanationLevel(exp_lvl_str)
    except ValueError:
        exp_lvl = ExplanationLevel.MANAGER

    plan_dict = state.get("analysis_plan")
    plan = AnalysisPlan.model_validate(plan_dict) if plan_dict else None
    semantic_context = state.get("semantic_context")
    rag_evidence = state.get("rag_evidence", [])

    # Collect explicit warnings from plan and semantic context
    warnings: list[str] = list(plan.warnings) if plan and plan.warnings else []
    if semantic_context:
        if semantic_context.get("unsupported_dimensions"):
            ud = semantic_context.get("unsupported_dimensions")
            warnings.append(f"Dimension(s) {ud} are not supported by the registered analytical tools and were omitted.")
        if semantic_context.get("unsupported_filters"):
            uf = semantic_context.get("unsupported_filters")
            warnings.append(f"Filter(s) {uf} could not be applied because they are unsupported.")
        if semantic_context.get("is_ambiguous"):
            c_name = semantic_context.get("canonical_name", "standard metric")
            warnings.append(f"Query contained ambiguous KPI terminology resolved to canonical metric '{c_name}'.")

    provider = get_llm_provider()

    # Invoke structured explanation synthesis if supported
    if hasattr(provider, "explain_results_structured"):
        grounded_exp = provider.explain_results_structured(
            query=user_query,
            plan=plan,
            tool_results=tool_results,
            evidence=evidence,
            explanation_level=exp_lvl,
            business_context=business_context,
            semantic_context=semantic_context,
            warnings=warnings,
            rag_evidence=rag_evidence,
        )
    else:
        raw_text = provider.explain_results(
            query=user_query,
            plan=plan,
            tool_results=tool_results,
            evidence=evidence,
            explanation_level=exp_lvl,
            business_context=business_context,
        )
        from app.agents.state.models import GroundedExplanation
        grounded_exp = GroundedExplanation(
            narrative=raw_text,
            warnings=warnings,
            is_fallback=bool(state.get("is_fallback", False)),
            fallback_reason=state.get("fallback_reason"),
        )

    # Sync state fallback status to grounded explanation
    if state.get("is_fallback"):
        grounded_exp.is_fallback = True
        if not grounded_exp.fallback_reason:
            grounded_exp.fallback_reason = state.get("fallback_reason")

    explanation = grounded_exp.to_formatted_text(exp_lvl)

    # Disclose business context ambiguity / definition conflicts if detected
    if state.get("has_business_context_conflict"):
        conflict_msg = state.get("business_context_conflict_description") or (
            "Conflicting business definitions were detected across retrieved context sources."
        )
        explanation = f"⚠️ **Context Conflict / Ambiguity Alert**: {conflict_msg}\n\n{explanation}"

    # Attach RAG provenance citations if available and not yet present
    if rag_evidence and "Business Context Sources" not in explanation and "(ID:" not in explanation:
        sources_list = []
        for ev in rag_evidence:
            title_part = f" — {ev.get('title')}" if ev.get("title") else ""
            sources_list.append(f"• {ev.get('document_name')}{title_part} (ID: {ev.get('document_id')})")
        if sources_list:
            explanation += "\n\n**Business Context Sources:**\n" + "\n".join(sources_list)

    # Disclose transparent fallback status if applicable
    if state.get("is_fallback") or grounded_exp.is_fallback:
        reason_msg = grounded_exp.fallback_reason or state.get("fallback_reason") or "deterministic baseline rules applied"
        if "Notice:" not in explanation:
            explanation += f"\n\n*Notice: Analysis generated using deterministic baseline rules ({reason_msg}).*"

    # Generate contextual follow-up questions
    follow_ups: list[str] = []
    tools_used = state.get("tools_used", [])

    if "get_financial_summary" in tools_used:
        follow_ups.append("Would you like to see which products or categories contributed most to this revenue?")
        follow_ups.append("Should we inspect monthly revenue trend over the past 6 months?")
    elif "run_variance_analysis" in tools_used:
        follow_ups.append("Would you like to run a Price/Volume/Mix decomposition on this change?")
        follow_ups.append("Should we analyze customer segment retention during this interval?")
    elif "get_product_rankings" in tools_used:
        follow_ups.append("Would you like to check inventory stock and turnover for these top products?")
        follow_ups.append("Should we examine product profit margins and unit cost breakdowns?")
    elif "get_inventory_overview" in tools_used:
        follow_ups.append("Would you like to identify slow-moving or dormant inventory items?")
        follow_ups.append("Should we review the inventory turnover ratio and DSI for the period?")
    elif "get_business_profile" in tools_used:
        follow_ups.append("Would you like to review our commercial revenue performance?")
        follow_ups.append("Should we inspect current data health and uploaded datasets?")
    else:
        follow_ups.append("Would you like to compare these figures with the previous period?")
        follow_ups.append("Should we generate a visual timeseries breakdown?")

    sanitized_answer = CausalitySafeguard.sanitize_diagnostic_text(explanation)

    merged_limitations = list(dict.fromkeys(state.get("limitations", []) + grounded_exp.limitations))

    return {
        "final_answer": sanitized_answer,
        "follow_up_questions": follow_ups,
        "is_fallback": bool(state.get("is_fallback", False) or grounded_exp.is_fallback),
        "fallback_reason": grounded_exp.fallback_reason or state.get("fallback_reason"),
        "llm_provider_name": grounded_exp.llm_provider or state.get("llm_provider_name"),
        "llm_model_name": grounded_exp.llm_model or state.get("llm_model_name"),
        "grounded_explanation": grounded_exp.model_dump(),
        "limitations": merged_limitations,
    }
