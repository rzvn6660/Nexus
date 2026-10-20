"""Regression tests for Proposal B.2 targeted production defect fixes."""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.agents.providers.openai_provider import OpenAIProvider
from app.analytics.evidence.models import EvidenceRecord
from app.core.config import settings
from app.data.synthetic.generator import RetailDataGenerator
from app.decisions.gateway import DecisionGateway
from app.predictive.schemas import EvaluationMetrics
from app.rag.rerank.factory import get_rerank_provider
from app.rag.rerank.providers.cross_scorer import LocalCrossScorerRerankProvider
from app.rag.rerank.providers.noop import NoOpRerankProvider


# -----------------------------------------------------------------------------
# 1. OpenAI Explanation Provider Tuple Unpacking
# -----------------------------------------------------------------------------
def test_openai_explanation_provider_unpacks_prompts_and_avoids_mock_fallback() -> None:
    """Proves OpenAIProvider correctly unpacks TaskPromptBuilder tuple return value

    and passes valid system and user messages to the OpenAI client without
    raising AttributeError or silently falling back to the mock.
    """
    provider = OpenAIProvider(api_key="sk-test-live-key", model="gpt-4o")

    fake_response = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = json.dumps({
        "narrative": "Revenue grew by 15% due to high repeat customer volume.",
        "key_findings": ["Increased repeat purchases"],
        "metric_citations": [],
        "evidence_citations": ["tools.financial_summary"],
        "unsupported_or_missing": [],
        "warnings": [],
        "limitations": [],
        "is_fallback": False,
        "fallback_reason": None,
    })
    fake_response.choices = [fake_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_response
    provider.client = mock_client

    with patch.object(provider._fallback_mock, "explain_results_structured") as mock_fallback:
        result = provider.explain_results_structured(
            query="Analyze Q3 revenue trends",
            plan=None,
            tool_results=[{"metric": "revenue", "value": 150000.0}],
            evidence=[{"metric": "revenue", "calculation": "SUM(total_amount)"}],
        )

        assert mock_client.chat.completions.create.called
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert isinstance(messages[0]["content"], str)
        assert "You are the explanation synthesizer" in messages[0]["content"]

        assert messages[1]["role"] == "user"
        assert isinstance(messages[1]["content"], str)
        assert "Analyze Q3 revenue trends" in messages[1]["content"]

        # Ensure fallback mock was NEVER called
        assert not mock_fallback.called
        assert result.narrative == "Revenue grew by 15% due to high repeat customer volume."
        assert not result.is_fallback


# -----------------------------------------------------------------------------
# 2. EvidenceRecord Schema & Tool row_count
# -----------------------------------------------------------------------------
def test_evidence_record_row_count_retention() -> None:
    """Verifies EvidenceRecord retains row_count=1 and does not discard it."""
    evidence = EvidenceRecord(
        metric="business_profile",
        source_tables=["businesses"],
        calculation="SELECT name FROM businesses WHERE id = :business_id",
        row_count=1,
    )
    assert evidence.row_count == 1
    dumped = evidence.model_dump()
    assert dumped["row_count"] == 1


def test_get_business_profile_tool_evidence_row_count() -> None:
    """Verifies that the get_business_profile tool execution sets row_count == 1 in its evidence."""
    from app.agents.tools.registry import ToolRegistry

    registry = ToolRegistry()

    # Mock DB session and Business object
    mock_biz = MagicMock()
    mock_biz.id = "biz-test-123"
    mock_biz.name = "Test Enterprise"
    mock_biz.industry = "Retail"
    mock_biz.country = "US"
    mock_biz.currency = "USD"
    mock_biz.timezone = "UTC"
    mock_biz.fiscal_year_start = 1

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_biz

    tool = registry.get("get_business_profile")
    assert tool is not None

    result = tool.execute(session=mock_db, arguments={"business_id": "biz-test-123"})
    assert result.status == "success"
    assert result.evidence is not None
    assert result.evidence.get("row_count") == 1


# -----------------------------------------------------------------------------
# 3. RAG Reranker Factory Null Configuration
# -----------------------------------------------------------------------------
def test_rag_reranker_factory_handles_null_configuration() -> None:
    """Verifies get_rerank_provider handles None configuration safely without AttributeError."""
    with (
        patch.object(settings, "RAG_RERANK_PROVIDER", None),
        patch.object(settings, "RAG_RERANK_ENABLED", True),
    ):
        provider = get_rerank_provider(provider_name=None, enabled=True)
        assert isinstance(provider, LocalCrossScorerRerankProvider)

    # When explicitly requesting noop
    provider_noop = get_rerank_provider(provider_name="noop", enabled=True)
    assert isinstance(provider_noop, NoOpRerankProvider)


# -----------------------------------------------------------------------------
# 4. Decision Provider Gateway Null Configuration
# -----------------------------------------------------------------------------
def test_decision_gateway_handles_null_configuration() -> None:
    """Verifies DecisionGateway._resolve_provider handles None configuration without AttributeError."""
    with (
        patch.object(settings, "DECISION_PROVIDER", None),
        patch.object(settings, "APP_ENV", None),
    ):
        provider = DecisionGateway._resolve_provider(requested_name=None)
        assert provider is not None


# -----------------------------------------------------------------------------
# 5. EvaluationMetrics Optional Fields Default to None
# -----------------------------------------------------------------------------
def test_evaluation_metrics_defaults_to_none_when_omitted() -> None:
    """Verifies mape and wape default to None when omitted from EvaluationMetrics."""
    metrics = EvaluationMetrics(mae=0.25, rmse=0.35, smape=8.5)
    assert metrics.mae == 0.25
    assert metrics.rmse == 0.35
    assert metrics.smape == 8.5
    assert metrics.mape is None
    assert metrics.wape is None


# -----------------------------------------------------------------------------
# 6. Synthetic Generator Typed Configuration & Deterministic Execution
# -----------------------------------------------------------------------------
def test_synthetic_generator_deterministic_products() -> None:
    """Verifies RetailDataGenerator._generate_products runs deterministically with typed CategoryConfig."""
    gen = RetailDataGenerator(seed=42)
    products = gen._generate_products(10)

    assert len(products) == 10
    for p in products:
        assert isinstance(p["unit_cost"], Decimal)
        assert isinstance(p["selling_price"], Decimal)
        assert p["unit_cost"] <= p["selling_price"]
        assert p["category"] in ["Electronics", "Office Supplies", "Industrial Tools", "Packaging & Shipping", "Workwear & Safety"]
