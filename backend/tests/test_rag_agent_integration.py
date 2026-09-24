"""Comprehensive integration tests for Agent with Business Context RAG and Semantic Layer.

Verifies the 6 foundational business workflows specified in Phase 5:
1. Exact KPI Query
2. Pure Business Definition (Zero numerical tools executed)
3. Calculation + Definition (Coexistence of Analytics Evidence and RAG Evidence)
4. Ambiguous Business Term (Clarification prompt)
5. Policy Context Retrieval
6. Unsupported Metric Rejection
"""

import pytest
from app.agents.service import NexusAgentService
from app.rag.ingestion.models import DocumentMetadata
from app.rag.ingestion.service import DocumentIngestionService
from sqlalchemy.orm import Session


@pytest.fixture
def seeded_knowledge_base(seeded_db_session: Session) -> Session:
    """Ingest sample retail documents for agent context retrieval tests."""
    service = DocumentIngestionService(seeded_db_session)

    # 1. Retail KPI definitions
    service.ingest_text(
        """## Gross Margin Definition
Gross margin expresses gross profit as a percentage of net revenue: `(Gross Profit / Net Revenue) * 100`.
It measures fundamental product sourcing profitability and margin efficiency.

## Net Revenue Definition
Net revenue represents total realized revenue after deducting promotional discounts and price concessions.
""",
        doc_type="markdown",
        metadata=DocumentMetadata(
            title="Retail KPI Definitions",
            business_domain="finance",
            source="retail_kpi_definitions.md",
        ),
    )

    # 2. Customer segments policy
    service.ingest_text(
        """## Repeat Customer Definition
In NEXUS, a Repeat Customer is officially defined as any customer account that has completed two (2) or more distinct orders across their lifetime.
Customers with exactly one completed purchase are designated as One-Time Buyers.
""",
        doc_type="markdown",
        metadata=DocumentMetadata(
            title="Customer Segmentation Policy",
            business_domain="customer",
            source="customer_segments.md",
        ),
    )

    return seeded_db_session


def test_agent_case_1_exact_kpi(seeded_knowledge_base: Session):
    """
    CASE 1 — Exact KPI:
    User asks: 'What was our net revenue last month?'
    Expected:
    - Semantic resolution: net_revenue
    - Analytics tool: get_financial_summary
    - Deterministic numerical evidence record returned
    """
    service = NexusAgentService(seeded_knowledge_base)
    response = service.run_analysis("What was our net revenue last month?")

    assert response.status == "completed"
    assert response.semantic_context is not None
    assert response.semantic_context.get("canonical_name") == "net_revenue"
    assert "get_financial_summary" in response.tools_used
    assert len(response.evidence) >= 1
    assert any(e.metric == "financial_summary" for e in response.evidence)


def test_agent_case_2_business_definition(seeded_knowledge_base: Session):
    """
    CASE 2 — Business Definition:
    User asks: 'What does gross margin mean in our business?'
    Expected:
    - Semantic resolution: gross_margin
    - RAG retrieval provides gross margin definition
    - No numerical calculation required (no tools executed)
    - RAG evidence populated in AgentResponse
    """
    service = NexusAgentService(seeded_knowledge_base)
    response = service.run_analysis("What does gross margin mean in our business?")

    assert response.status == "completed"
    assert len(response.tools_used) == 0  # No tool execution required!
    assert len(response.rag_evidence) >= 1
    assert "Gross Margin" in response.answer or "gross profit" in response.answer.lower()
    assert response.semantic_context is not None
    assert response.semantic_context.get("canonical_name") == "gross_margin"


def test_agent_case_3_definition_plus_calculation(seeded_knowledge_base: Session):
    """
    CASE 3 — Definition + Number:
    User asks: 'What was our gross margin last month and what does it mean?'
    Expected:
    - Resolves gross_margin
    - Retrieves business definition
    - Executes deterministic analytics tool
    - Combines result + business definition in explanation
    - Preserves both Analytics EvidenceRecord and RAGEvidence
    """
    service = NexusAgentService(seeded_knowledge_base)
    response = service.run_analysis("What was our gross margin last month and what does it mean?")

    assert response.status == "completed"
    assert "get_financial_summary" in response.tools_used
    assert len(response.evidence) >= 1  # Analytics evidence
    assert len(response.rag_evidence) >= 1  # RAG evidence
    assert "Gross Margin" in response.answer


def test_agent_case_4_ambiguous_term(seeded_knowledge_base: Session):
    """
    CASE 4 — Ambiguous Term:
    User asks: 'What is our turnover?'
    Expected:
    - Detect ambiguity between Net Revenue and Inventory Turnover
    - Does not blindly guess or execute
    - Asks for clarification
    """
    service = NexusAgentService(seeded_knowledge_base)
    response = service.run_analysis("What is our turnover?")

    assert response.status == "clarification_needed"
    assert response.needs_clarification is True
    assert response.clarification_prompt is not None
    assert "Net Revenue" in response.clarification_prompt
    assert "Inventory Turnover" in response.clarification_prompt
    assert len(response.tools_used) == 0


def test_agent_case_5_policy_context(seeded_knowledge_base: Session):
    """
    CASE 5 — Policy Context:
    User asks: 'How do we define a repeat customer?'
    Expected:
    - Retrieves customer segmentation policy context
    - Does not invent definition
    - Cites RAG evidence
    """
    service = NexusAgentService(seeded_knowledge_base)
    response = service.run_analysis("How do we define a repeat customer?")

    assert response.status == "completed"
    assert len(response.rag_evidence) >= 1
    assert "two" in response.answer.lower() or "2" in response.answer
    assert any("Customer Segmentation Policy" in e.document_name for e in response.rag_evidence)


def test_agent_case_6_unsupported_term(seeded_knowledge_base: Session):
    """
    CASE 6 — Unsupported Term:
    User asks: 'What is our customer lifetime value?'
    Expected:
    - Does not fabricate metric
    - Rejects with clear message that CLV is not currently supported
    """
    service = NexusAgentService(seeded_knowledge_base)
    response = service.run_analysis("What is our customer lifetime value?")

    assert response.status == "unsupported"
    assert "Customer Lifetime Value" in response.answer or "CLV" in response.answer
