"""Semantic resolution and context retrieval nodes for the LangGraph agent."""

import logging
import re
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.state.models import AgentState
from app.rag.retrieval.retriever import HybridRetriever
from app.rag.semantic.ontology import semantic_resolver

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


def semantic_resolution_node(state: AgentState) -> dict[str, Any]:
    """
    Resolve natural language terms against the NEXUS KPI ontology.
    Detects ambiguous business terms and explicitly unsupported metrics before planning.
    """
    user_query = state.get("user_query", "").strip()
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
        retrieved_context = retriever.retrieve(user_query, business_domain=resolved_domain)
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
    if retrieved_context:
        rag_evidence_dicts = [e.model_dump() for e in retrieved_context.evidence]
        context_text = retrieved_context.context_text

    # Check if query is purely definitional (no tool execution required)
    is_definitional_only = _is_definitional_only_query(user_query)

    return {
        "rag_evidence": rag_evidence_dicts,
        "business_context_text": context_text,
        "is_definitional_only": is_definitional_only,
    }
