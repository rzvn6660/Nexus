"""Comprehensive unit and integration test suite for the NEXUS Decision Gateway abstraction."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.decisions import (
    BaseDecisionProvider,
    DecisionError,
    DecisionGateway,
    DecisionProviderUnavailableError,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionTask,
    DecisionTelemetry,
    DecisionTimeoutError,
    DecisionValidationError,
    InvalidDecisionProviderError,
    JevDecisionProvider,
    MalformedDecisionResponseError,
    MockDecisionProvider,
    StructuredLLMDecisionProvider,
    UnsupportedDecisionTaskError,
    get_decision_gateway,
)


class TestDecisionModels:
    """Test suite 1 & 2: DecisionRequest & DecisionResult validation."""

    def test_decision_request_valid(self):
        req = DecisionRequest(
            task=DecisionTask.INTENT_ROUTING,
            input_text="What was our revenue in Q3?",
            candidate_options=["metric_lookup", "trend", "diagnostic_analysis"],
            context={"fiscal_year": 2024},
            metadata={"request_id": "REQ-123"},
        )
        assert req.task == DecisionTask.INTENT_ROUTING
        assert req.input_text == "What was our revenue in Q3?"
        assert len(req.candidate_options) == 3
        assert req.context["fiscal_year"] == 2024
        assert req.metadata["request_id"] == "REQ-123"

    def test_decision_result_valid_with_honest_confidence(self):
        telemetry = DecisionTelemetry(
            provider="mock",
            latency_ms=12.5,
            tokens_used=150,
            estimated_cost_usd=0.0003,
        )
        res = DecisionResult(
            task="intent_routing",
            status=DecisionStatus.SUCCESS,
            decision="metric_lookup",
            structured_output={"category": "metric_lookup"},
            rationale="Query asks for direct aggregation",
            confidence=0.98,
            telemetry=telemetry,
        )
        assert res.decision == "metric_lookup"
        assert res.confidence == 0.98
        assert res.telemetry.latency_ms == 12.5

    def test_decision_result_missing_confidence_is_none(self):
        """Rule: Never invent fake confidence. When unavailable, it must be None."""
        telemetry = DecisionTelemetry(provider="mock", latency_ms=5.0)
        res = DecisionResult(
            task="tool_selection",
            status=DecisionStatus.SUCCESS,
            decision="get_financial_summary",
            structured_output={"tool": "get_financial_summary"},
            confidence=None,
            telemetry=telemetry,
        )
        assert res.confidence is None

    def test_decision_result_rejects_invalid_confidence_range(self):
        telemetry = DecisionTelemetry(provider="mock", latency_ms=5.0)
        with pytest.raises(ValidationError):
            DecisionResult(
                task="test",
                decision="val",
                confidence=1.5,  # Must be le 1.0
                telemetry=telemetry,
            )


class TestMockDecisionProvider:
    """Test suite 5: Mock Decision Provider deterministic behavior and overrides."""

    def test_mock_intent_routing_deterministic(self):
        mock = MockDecisionProvider()
        req = DecisionRequest(
            task=DecisionTask.INTENT_ROUTING,
            input_text="Why did our profit drop last month?",
            candidate_options=["metric_lookup", "diagnostic_analysis", "forecasting"],
        )
        res = mock.execute_decision(req)
        assert res.status == DecisionStatus.SUCCESS
        assert res.decision == "diagnostic_analysis"
        assert res.telemetry.latency_ms >= 0.0

    def test_mock_tool_selection_deterministic(self):
        mock = MockDecisionProvider()
        req = DecisionRequest(
            task=DecisionTask.TOOL_SELECTION,
            input_text="Give me financial numbers",
            candidate_options=["get_financial_summary", "run_variance_analysis"],
        )
        res = mock.execute_decision(req)
        assert res.status == DecisionStatus.SUCCESS
        assert res.decision == "get_financial_summary"

    def test_mock_evidence_sufficiency_deterministic(self):
        mock = MockDecisionProvider()
        req_sufficient = DecisionRequest(
            task=DecisionTask.EVIDENCE_SUFFICIENCY,
            input_text="Check results",
            context={"tool_results": [{"status": "success", "result": {"revenue": 100}}]},
        )
        res = mock.execute_decision(req_sufficient)
        assert res.decision == "SUFFICIENT"

        req_insufficient = DecisionRequest(
            task=DecisionTask.EVIDENCE_SUFFICIENCY,
            input_text="Check results",
            context={"tool_results": []},
        )
        res2 = mock.execute_decision(req_insufficient)
        assert res2.decision == "INSUFFICIENT"

    def test_mock_configurable_response_override(self):
        mock = MockDecisionProvider()
        custom_res = DecisionResult(
            task="intent_routing",
            status=DecisionStatus.SUCCESS,
            decision="custom_override_intent",
            telemetry=DecisionTelemetry(provider="mock", latency_ms=1.0),
        )
        mock.set_response(DecisionTask.INTENT_ROUTING, custom_res)

        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="What was our total revenue?")
        res = mock.execute_decision(req)
        assert res.decision == "custom_override_intent"

        # Clear overrides restores default behavior
        mock.clear_overrides()
        res_default = mock.execute_decision(req)
        assert res_default.decision == "metric_lookup"

    def test_mock_simulated_error(self):
        mock = MockDecisionProvider()
        mock.set_error(DecisionTask.INTENT_ROUTING, "Simulated database connection crash")

        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="anything")
        with pytest.raises(DecisionProviderUnavailableError) as exc_info:
            mock.execute_decision(req)
        assert "Simulated database connection crash" in str(exc_info.value)

    def test_mock_simulated_timeout(self):
        mock = MockDecisionProvider()
        mock.set_timeout(DecisionTask.INTENT_ROUTING)

        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="anything")
        with pytest.raises(DecisionTimeoutError) as exc_info:
            mock.execute_decision(req)
        assert "timed out" in str(exc_info.value)


class TestStructuredLLMProvider:
    """Test suite 4, 7, 8, 9, 13: Structured LLM provider and production safety invariants."""

    def test_structured_llm_missing_credentials_raises_error(self):
        """CRITICAL: Missing credentials in live mode must RAISE, never silently pretend mock."""
        provider = StructuredLLMDecisionProvider(api_key=None)
        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="revenue query")

        with pytest.raises(DecisionProviderUnavailableError) as exc_info:
            provider.execute_decision(req)
        assert "is unavailable" in str(exc_info.value)

    def test_structured_llm_successful_execution(self):
        provider = StructuredLLMDecisionProvider(api_key="sk-test-key-mock", model="gpt-4o")

        # Mock the underlying OpenAI client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "decision": "metric_lookup",
                "confidence": 0.95,
                "reasoning": "Query asks for single KPI lookup"
            })))
        ]
        mock_response.usage.prompt_tokens = 120
        mock_response.usage.completion_tokens = 25
        mock_response.usage.total_tokens = 145
        mock_client.chat.completions.create.return_value = mock_response

        provider._client = mock_client

        req = DecisionRequest(
            task=DecisionTask.INTENT_ROUTING,
            input_text="What was our gross revenue last month?",
            candidate_options=["metric_lookup", "trend", "forecasting"],
        )
        res = provider.execute_decision(req)

        assert res.status == DecisionStatus.SUCCESS
        assert res.decision == "metric_lookup"
        assert res.confidence == 0.95
        assert res.telemetry.tokens_used == 145
        assert res.telemetry.prompt_tokens == 120
        assert res.telemetry.completion_tokens == 25
        assert res.telemetry.estimated_cost_usd is not None
        assert res.telemetry.estimated_cost_usd > 0.0

    def test_structured_llm_malformed_json_raises_error(self):
        provider = StructuredLLMDecisionProvider(api_key="sk-test-key-mock")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="NON_JSON_PROSE_TEXT"))]
        mock_client.chat.completions.create.return_value = mock_response
        provider._client = mock_client

        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="test")
        with pytest.raises(MalformedDecisionResponseError):
            provider.execute_decision(req)

    def test_structured_llm_timeout_raises_timeout_error(self):
        provider = StructuredLLMDecisionProvider(api_key="sk-test-key-mock")
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Request timed out after 10.0 seconds")
        provider._client = mock_client

        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="test")
        with pytest.raises(DecisionTimeoutError):
            provider.execute_decision(req)

    def test_live_llm_failure_does_not_silently_fallback_to_mock(self):
        """CRITICAL PRODUCTION SAFETY RULE: Live LLM failure must raise, never pretend mock is real."""
        provider = StructuredLLMDecisionProvider(api_key="sk-test-key-mock")
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Connection refused by OpenAI")
        provider._client = mock_client

        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="test")
        with pytest.raises(DecisionProviderUnavailableError) as exc_info:
            provider.execute_decision(req)
        assert "API Connection refused" in str(exc_info.value)


class TestDecisionGatewayOrchestration:
    """Test suite 3, 6, 12, 14: Gateway provider resolution and high-level interface."""

    def test_gateway_resolves_mock_provider(self):
        gateway = DecisionGateway(provider_name="mock")
        assert gateway.provider_name == "mock"
        assert isinstance(gateway.active_provider, MockDecisionProvider)

    def test_gateway_resolves_structured_llm_provider(self):
        gateway = DecisionGateway(provider_name="structured_llm")
        assert gateway.provider_name == "structured_llm"
        assert isinstance(gateway.active_provider, StructuredLLMDecisionProvider)

    def test_gateway_rejects_invalid_provider_name(self):
        with pytest.raises(InvalidDecisionProviderError) as exc_info:
            DecisionGateway(provider_name="unsupported_quantum_ai")
        assert "Unknown decision provider" in str(exc_info.value)

    def test_gateway_resolves_jev_provider(self):
        """Confirm DecisionGateway successfully resolves JevDecisionProvider in Phase 12B."""
        gateway = DecisionGateway(provider_name="jev")
        assert gateway.provider_name == "jev"
        assert isinstance(gateway.active_provider, JevDecisionProvider)

    def test_gateway_validates_empty_request(self):
        gateway = DecisionGateway(provider=MockDecisionProvider())
        with pytest.raises(DecisionValidationError):
            gateway.decide(DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text=""))

    def test_gateway_candidate_option_mismatch_marks_degraded(self):
        mock = MockDecisionProvider()
        mock.set_response(
            DecisionTask.INTENT_ROUTING,
            DecisionResult(
                task="intent_routing",
                status=DecisionStatus.SUCCESS,
                decision="wildcard_unlisted_option",
                telemetry=DecisionTelemetry(provider="mock"),
            )
        )
        gateway = DecisionGateway(provider=mock)
        res = gateway.route_intent("test", ["metric_lookup", "trend"])
        assert res.status == DecisionStatus.DEGRADED
        assert "not in candidate_options" in str(res.error_message)

    def test_gateway_route_intent_convenience(self):
        gateway = DecisionGateway(provider=MockDecisionProvider())
        res = gateway.route_intent("What is the sales breakdown?", ["metric_lookup", "comparison"])
        assert res.task == DecisionTask.INTENT_ROUTING.value
        assert res.decision in ["metric_lookup", "comparison"]

    def test_gateway_select_tools_convenience(self):
        gateway = DecisionGateway(provider=MockDecisionProvider())
        res = gateway.select_tools("financial summary", ["get_financial_summary", "run_variance_analysis"])
        assert res.task == DecisionTask.TOOL_SELECTION.value
        assert res.decision == "get_financial_summary"

    def test_gateway_rerank_context_convenience(self):
        gateway = DecisionGateway(provider=MockDecisionProvider())
        chunks = [{"chunk_id": "c1"}, {"chunk_id": "c2"}, {"chunk_id": "c3"}, {"chunk_id": "c4"}]
        res = gateway.rerank_context("query", chunks, top_k=2)
        assert res.task == DecisionTask.RAG_RERANKING.value
        assert len(res.structured_output["ranked_items"]) == 2

    def test_gateway_evaluate_evidence_convenience(self):
        gateway = DecisionGateway(provider=MockDecisionProvider())
        res = gateway.evaluate_evidence("query", [], [{"status": "success"}])
        assert res.task == DecisionTask.EVIDENCE_SUFFICIENCY.value
        assert res.decision == "SUFFICIENT"

    def test_gateway_assess_risk_convenience(self):
        gateway = DecisionGateway(provider=MockDecisionProvider())
        res = gateway.assess_risk("Increase marketing spend by 10%")
        assert res.task == DecisionTask.RISK_GATING.value
        assert res.decision == "LOW"

    def test_get_decision_gateway_singleton(self):
        g1 = get_decision_gateway()
        g2 = get_decision_gateway()
        assert g1 is g2


class TestJevDecisionProvider:
    """Test suite: Jev System-1 decision provider adapter and safety invariants."""

    def test_jev_missing_credentials_raises_error(self):
        """CRITICAL: Missing credentials in live Jev mode must RAISE, never silently fallback."""
        provider = JevDecisionProvider(api_key=None, client=None)
        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="revenue query")

        with pytest.raises(DecisionProviderUnavailableError) as exc_info:
            provider.execute_decision(req)
        assert "unavailable" in str(exc_info.value)

    def test_jev_health_check(self):
        provider_no_key = JevDecisionProvider(api_key=None, client=None)
        assert provider_no_key.health_check() is False

        mock_client = MagicMock()
        provider_with_client = JevDecisionProvider(client=mock_client)
        assert provider_with_client.health_check() is True

    def test_jev_valid_intent_routing(self):
        mock_client = MagicMock()
        mock_answer = MagicMock()
        mock_answer.choice = "metric_lookup"
        mock_answer.confidence = 0.96
        mock_answer.probabilities = {"metric_lookup": 0.96, "trend": 0.04}

        mock_response = MagicMock()
        mock_response.model = "jev-latest"
        mock_response.answers = {"intent": mock_answer}
        mock_response.usage.input_tokens = 45
        mock_response.usage.output_tokens = 5
        mock_client.system_one.return_value = mock_response

        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(
            task=DecisionTask.INTENT_ROUTING,
            input_text="What was our total revenue last month?",
            candidate_options=["metric_lookup", "trend", "forecasting"],
        )
        res = provider.execute_decision(req)

        assert res.status == DecisionStatus.SUCCESS
        assert res.decision == "metric_lookup"
        assert res.confidence == 0.96
        assert res.telemetry.provider == "jev"
        assert res.telemetry.model == "jev-latest"
        assert res.telemetry.tokens_used == 50
        assert res.telemetry.prompt_tokens == 45
        assert res.telemetry.completion_tokens == 5
        assert res.telemetry.estimated_cost_usd is None  # Cost is not fabricated
        assert res.telemetry.metadata["probabilities"] == {"metric_lookup": 0.96, "trend": 0.04}

    def test_jev_candidate_boundary_enforcement(self):
        """Rule: If Jev produces an invalid candidate, mark DEGRADED and never silently substitute."""
        mock_client = MagicMock()
        mock_answer = MagicMock()
        mock_answer.choice = "hallucinated_unknown_intent"
        mock_answer.confidence = 0.88
        mock_answer.probabilities = None

        mock_response = MagicMock()
        mock_response.answers = {"intent": mock_answer}
        mock_response.usage = None
        mock_client.system_one.return_value = mock_response

        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(
            task=DecisionTask.INTENT_ROUTING,
            input_text="What was our revenue?",
            candidate_options=["metric_lookup", "trend"],
        )
        res = provider.execute_decision(req)

        assert res.status == DecisionStatus.DEGRADED
        assert res.decision == "hallucinated_unknown_intent"
        assert "not in candidate_options" in str(res.error_message)

    def test_jev_missing_confidence_is_none(self):
        """Rule: Never invent confidence. When unavailable, it must be None."""
        mock_client = MagicMock()
        mock_answer = MagicMock()
        mock_answer.choice = "metric_lookup"
        mock_answer.confidence = None
        mock_answer.probabilities = None

        mock_response = MagicMock()
        mock_response.answers = {"intent": mock_answer}
        mock_response.usage = None
        mock_client.system_one.return_value = mock_response

        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="What was our revenue?")
        res = provider.execute_decision(req)

        assert res.status == DecisionStatus.SUCCESS
        assert res.confidence is None

    def test_jev_malformed_response_missing_answer_raises(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.answers = {}  # Empty answers dict
        mock_client.system_one.return_value = mock_response

        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="test query")

        with pytest.raises(MalformedDecisionResponseError) as exc_info:
            provider.execute_decision(req)
        assert "missing answer key" in str(exc_info.value)

    def test_jev_timeout_raises_decision_timeout_error(self):
        mock_client = MagicMock()
        mock_client.system_one.side_effect = Exception("SystemOne execution timed out after 10.0 seconds")

        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="test query")

        with pytest.raises(DecisionTimeoutError) as exc_info:
            provider.execute_decision(req)
        assert "timed out" in str(exc_info.value)

    def test_live_jev_failure_does_not_silently_fallback(self):
        """CRITICAL: Live Jev failure must raise, never pretend mock is real."""
        mock_client = MagicMock()
        mock_client.system_one.side_effect = Exception("Connection refused by TypeSafe API gateway")

        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(task=DecisionTask.INTENT_ROUTING, input_text="test query")

        with pytest.raises(DecisionProviderUnavailableError) as exc_info:
            provider.execute_decision(req)
        assert "Connection refused" in str(exc_info.value)

    def test_jev_unsupported_task_raises_error(self):
        mock_client = MagicMock()
        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(task="unknown_unsupported_task", input_text="test query")

        with pytest.raises(UnsupportedDecisionTaskError):
            provider.execute_decision(req)

    def test_jev_tool_selection(self):
        mock_client = MagicMock()
        mock_answer = MagicMock()
        mock_answer.choice = "get_financial_summary"
        mock_answer.confidence = 0.92
        mock_answer.probabilities = None

        mock_response = MagicMock()
        mock_response.answers = {"tool": mock_answer}
        mock_response.usage = None
        mock_client.system_one.return_value = mock_response

        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(
            task=DecisionTask.TOOL_SELECTION,
            input_text="Give me total sales",
            candidate_options=["get_financial_summary", "run_variance_analysis"],
        )
        res = provider.execute_decision(req)

        assert res.status == DecisionStatus.SUCCESS
        assert res.decision == "get_financial_summary"
        assert res.structured_output["selected_tools"] == ["get_financial_summary"]

    def test_jev_evidence_sufficiency(self):
        mock_client = MagicMock()
        mock_answer = MagicMock()
        mock_answer.choice = "SUFFICIENT"
        mock_answer.confidence = 0.98
        mock_answer.probabilities = None

        mock_response = MagicMock()
        mock_response.answers = {"sufficiency": mock_answer}
        mock_response.usage = None
        mock_client.system_one.return_value = mock_response

        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(
            task=DecisionTask.EVIDENCE_SUFFICIENCY,
            input_text="Did we find the revenue numbers?",
            context={"tool_results": [{"revenue": 500000}]},
        )
        res = provider.execute_decision(req)

        assert res.status == DecisionStatus.SUCCESS
        assert res.decision == "SUFFICIENT"

    def test_jev_risk_gating(self):
        mock_client = MagicMock()
        mock_answer = MagicMock()
        mock_answer.choice = "HIGH"
        mock_answer.confidence = 0.85
        mock_answer.probabilities = None

        mock_response = MagicMock()
        mock_response.answers = {"risk": mock_answer}
        mock_response.usage = None
        mock_client.system_one.return_value = mock_response

        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(
            task=DecisionTask.RISK_GATING,
            input_text="Liquidate entire inventory immediately",
            candidate_options=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
        )
        res = provider.execute_decision(req)

        assert res.status == DecisionStatus.SUCCESS
        assert res.decision == "HIGH"
