"""Semantic resolution and context retrieval nodes for the LangGraph agent."""

import logging
import re
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.state.models import AgentState
from app.rag.retrieval.retriever import HybridRetriever
from app.rag.semantic.ontology import kpi_ontology, semantic_resolver

logger = logging.getLogger(__name__)


def _is_definitional_only_query(query: str) -> bool:
    """
    Detect if the user query is purely asking for business meaning/policy/definition
    without requesting specific numerical aggregation, dates, or time periods.
    """
    q = query.lower().strip()

    # If query contains explicit temporal keywords or comparison indicators, it's not definitional only
    temporal_indicators = [
        "last month", "this month", "last quarter", "this quarter", "last year", "this year",
        "yesterday", "today", "between", "from ", "to 20", "in 20", "compare", "growth",
        "trend", "decline", "increase", "breakdown by", "top 5", "top 10", "rankings"
    ]
    if any(t in q for t in temporal_indicators):
        return False

    # Check for definition question indicators
    definitional_patterns = [
        r"\bwhat does .+ mean\b",
        r"\bwhat is the definition of\b",
        r"\bwhat is our definition of\b",
        r"\bhow do we define\b",
        r"\bdefinition of\b",
        r"\bmeaning of\b",
        r"\bpolicy on\b",
        r"\bexplain the metric\b",
    ]
    for pattern in definitional_patterns:
        if re.search(pattern, q):
            return True

    return False


def semantic_resolution_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Resolve natural language terms against the tenant semantic model or canonical KPI ontology.
    Detects tenant metric availability states, ambiguous business terms, and unsupported metrics.
    """
    user_query = state.get("user_query", "").strip()
    intent_dict = state.get("intent") or {}
    if intent_dict.get("category") == "business_profile":
        return {
            "semantic_context": {"intent": "business_profile"},
            "is_unsupported": False,
            "needs_clarification": False,
        }

    business_id = state.get("business_id")
    session = None
    if config:
        configurable = config.get("configurable", {})
        session = configurable.get("session")

    # If tenant business and session are present, perform tenant-aware semantic resolution
    if business_id and session:
        from app.services.tenant_semantic_service import TenantSemanticService
        tenant_res = TenantSemanticService.resolve_query_with_tenant_context(
            query=user_query,
            business_id=business_id,
            db=session,
        )

        res_dict = tenant_res.model_dump()
        # Enrich with canonical KPI object if available
        if tenant_res.canonical_name:
            kpi_obj = kpi_ontology.get_kpi(tenant_res.canonical_name)
            if kpi_obj:
                res_dict["resolved_kpi"] = kpi_obj.model_dump()

        # 1. Explicit unsupported metric
        if not tenant_res.is_supported:
            return {
                "semantic_context": res_dict,
                "is_unsupported": True,
                "unsupported_reason": tenant_res.unsupported_message or (
                    "The requested metric is not currently supported by the NEXUS metric catalog."
                ),
                "evidence_status": "INSUFFICIENT",
            }

        # 2. Ambiguous business term requiring clarification
        if tenant_res.is_ambiguous:
            return {
                "semantic_context": res_dict,
                "needs_clarification": True,
                "clarification_question": tenant_res.clarification_prompt or (
                    "The specified term is ambiguous. Please clarify which metric you would like to analyze."
                ),
                "evidence_status": "INSUFFICIENT",
            }

        # 3. Metric availability state from tenant database grounding
        if tenant_res.availability_status == "REQUIRES_COST_DATA":
            return {
                "semantic_context": res_dict,
                "is_unsupported": True,
                "unsupported_reason": tenant_res.unsupported_message or (
                    "Gross Margin calculation requires cost data (unit cost or purchase price) which is not present in your catalog."
                ),
                "evidence_status": "INSUFFICIENT",
            }
        elif tenant_res.availability_status == "INSUFFICIENT_HISTORY":
            return {
                "semantic_context": res_dict,
                "is_unsupported": True,
                "unsupported_reason": tenant_res.unsupported_message or (
                    "This metric requires more transaction history than currently available in your dataset."
                ),
                "evidence_status": "INSUFFICIENT",
            }
        elif tenant_res.availability_status == "UNAVAILABLE" and tenant_res.canonical_kpi:
            return {
                "semantic_context": res_dict,
                "is_unsupported": True,
                "unsupported_reason": tenant_res.unsupported_message or (
                    "This metric is unavailable based on your currently uploaded records."
                ),
                "evidence_status": "INSUFFICIENT",
            }

        return {
            "semantic_context": res_dict,
            "is_unsupported": False,
            "needs_clarification": False,
        }

    # Canonical resolution fallback
    resolution = semantic_resolver.resolve(user_query)

    # 1. Check for explicit unsupported metric
    if not resolution.is_supported:
        return {
            "semantic_context": resolution.model_dump(),
            "is_unsupported": True,
            "unsupported_reason": resolution.unsupported_message or (
                "The requested metric is not currently supported by the NEXUS metric catalog."
            ),
            "evidence_status": "INSUFFICIENT",
        }

    # 2. Check for ambiguous business term
    if resolution.is_ambiguous:
        return {
            "semantic_context": resolution.model_dump(),
            "needs_clarification": True,
            "clarification_question": resolution.clarification_prompt or (
                "The specified term is ambiguous. Please clarify which metric you would like to analyze."
            ),
            "evidence_status": "INSUFFICIENT",
        }

    return {
        "semantic_context": resolution.model_dump(),
        "is_unsupported": False,
        "needs_clarification": False,
    }


def retrieve_context_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Retrieve verified business context, policy guidelines, and KPI definitions.
    Connects RAG evidence to agent state while isolating untrusted document content.
    """
    user_query = state.get("user_query", "").strip()
    intent_dict = state.get("intent") or {}
    if intent_dict.get("category") == "business_profile":
        return {
            "rag_evidence": [],
            "business_context_text": None,
            "is_definitional_only": False,
            "has_business_context_conflict": False,
            "business_context_conflict_description": None,
        }

    sem_context = state.get("semantic_context") or {}
    resolved_domain = None

    if sem_context.get("resolved_kpi"):
        resolved_domain = sem_context["resolved_kpi"].get("business_domain")

    # Extract session from LangGraph config if provided
    session = None
    if config:
        configurable = config.get("configurable", {})
        session = configurable.get("session")

    retrieved_context = None
    if session:
        retriever = HybridRetriever(session)
        retrieved_context = retriever.retrieve(
            user_query,
            business_domain=resolved_domain,
            business_id=state.get("business_id"),
        )
    else:
        # Fallback offline hybrid retriever using semantic ontology directly
        from app.rag.retrieval.models import RetrievedContext
        if sem_context.get("resolved_kpi"):
            kpi = sem_context["resolved_kpi"]
            kpi_content = (
                f"### {kpi['display_name']} Definition\n"
                f"**Business Meaning**: {kpi['description']}\n"
                f"**Calculation Formula**: {kpi['calculation_reference']}\n"
                f"**Unit**: {kpi['unit']} | **Domain**: {kpi['business_domain']}"
            )
            from app.rag.retrieval.models import RAGEvidence, RetrievedChunk
            chk = RetrievedChunk(
                chunk_id=f"kpi_{kpi['canonical_name']}",
                document_id="doc_kpi_ontology",
                document_title="NEXUS KPI Ontology Registry",
                source="system_kpi_ontology",
                title=kpi["display_name"],
                content=kpi_content,
                similarity=1.0,
                business_domain=kpi["business_domain"],
                retrieval_method="exact_kpi_match",
                metadata_json={"canonical_name": kpi["canonical_name"]},
            )
            ev = RAGEvidence(
                document_id=chk.document_id,
                document_name=chk.document_title,
                chunk_id=chk.chunk_id,
                source=chk.source,
                title=chk.title,
                similarity_score=1.0,
                retrieval_method="exact_kpi_match",
                excerpt=chk.content[:200],
            )
            retrieved_context = RetrievedContext(
                query=user_query,
                chunks=[chk],
                evidence=[ev],
                resolved_kpi_canonical=kpi["canonical_name"],
                retrieval_method="exact_kpi_match",
                context_text=kpi_content,
            )

    rag_evidence_dicts = []
    context_text = ""
    has_conflict = False
    conflict_desc = None
    if retrieved_context:
        rag_evidence_dicts = [e.model_dump() for e in retrieved_context.evidence]
        context_text = retrieved_context.context_text
        has_conflict = retrieved_context.has_conflict
        conflict_desc = retrieved_context.conflict_description

    # Check if query is purely definitional (no tool execution required)
    is_definitional_only = _is_definitional_only_query(user_query)

    return {
        "rag_evidence": rag_evidence_dicts,
        "business_context_text": context_text,
        "is_definitional_only": is_definitional_only,
        "has_business_context_conflict": has_conflict,
        "business_context_conflict_description": conflict_desc,
    }
