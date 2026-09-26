"""NEXUS Phase 13: Taxonomy Reconciliation & Decision Architecture Test Suite.

Validates the canonical intent taxonomy, legacy compatibility mappings,
tool reconciliation, candidate consistency across all four providers (Gateway, Structured LLM, Jev, Mock),
evaluation dataset integrity, and zero leakage verification.
"""

import json
import os
import pytest
from unittest.mock import MagicMock

from app.agents.state.models import IntentCategory, IntentResult
from app.agents.tools.registry import tool_registry
from app.decisions import (
    CanonicalIntent,
    DecisionGateway,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionTask,
    IntentDefinition,
    JevDecisionProvider,
    MockDecisionProvider,
    StructuredLLMDecisionProvider,
    get_canonical_intent_ids,
    get_decision_gateway,
    resolve_intent,
    resolve_tool,
    validate_intent_id,
)
from app.decisions.exemplars import (
    NEXUS_INTENT_EXEMPLARS,
    get_intent_exemplars,
    verify_zero_evaluation_leakage,
)
from app.decisions.taxonomy import (
    CANONICAL_INTENT_DEFINITIONS,
    LEGACY_INTENT_MAP,
    LEGACY_TOOL_MAP,
)


class TestCanonicalTaxonomyValidity:
    """Tests 1, 2, 3, 4: Canonical taxonomy schema, uniqueness, and completeness."""

    def test_canonical_taxonomy_validity(self):
        """Verify that all 12 canonical intents have complete definitions."""
        assert len(CANONICAL_INTENT_DEFINITIONS) == 12
        for intent_id, definition in CANONICAL_INTENT_DEFINITIONS.items():
            assert isinstance(definition, IntentDefinition)
            assert definition.id == intent_id
            assert len(definition.name) > 0
            assert len(definition.description) > 10
            assert len(definition.examples) >= 2
            assert len(definition.exclusions) >= 1
            assert len(definition.subtypes) >= 1
            assert len(definition.analytics_family) > 0

    def test_unique_intent_ids(self):
        """Verify intent IDs are unique and match CanonicalIntent enum members."""
        canonical_ids = [e.value for e in CanonicalIntent]
        assert len(canonical_ids) == len(set(canonical_ids))
        assert set(canonical_ids) == set(CANONICAL_INTENT_DEFINITIONS.keys())

    def test_candidate_generation(self):
        """Verify that candidate generation yields the authoritative canonical IDs."""
        ids = get_canonical_intent_ids()
        assert len(ids) == 12
        assert "metric_lookup" in ids
        assert "diagnostic_analysis" in ids
        assert "semantic_resolution" in ids
        assert "forecasting" in ids
        assert "unsupported" in ids

    def test_validate_intent_id_helper(self):
        """Verify intent validation helper distinguishes valid vs invalid IDs."""
        assert validate_intent_id("metric_lookup") is True
        assert validate_intent_id("diagnostic_analysis") is True
        assert validate_intent_id("non_existent_fake_intent") is False


class TestLegacyMappingsAndSubtypes:
    """Tests 5, 6, 12: Legacy alias mapping, subtype extraction, and tool reconciliation."""

    def test_legacy_intent_mapping(self):
        """Verify all historical fine-grained evaluation labels resolve to canonical IDs."""
        assert resolve_intent("ranking_lookup")[0] == "product_analysis"
        assert resolve_intent("category_breakdown")[0] == "product_analysis"
        assert resolve_intent("product_lookup")[0] == "product_analysis"
        assert resolve_intent("product_comparison")[0] == "comparison"
        assert resolve_intent("period_comparison")[0] == "comparison"
        assert resolve_intent("inventory_lookup")[0] == "inventory_analysis"
        assert resolve_intent("customer_lookup")[0] == "customer_analysis"
        assert resolve_intent("forecast_lookup")[0] == "forecasting"
        assert resolve_intent("semantic_resolution")[0] == "semantic_resolution"
        assert resolve_intent("unsupported")[0] == "unsupported"

    def test_subtype_handling(self):
        """Verify that subtype metadata is preserved during intent resolution."""
        canonical, subtype = resolve_intent("ranking_lookup")
        assert canonical == "product_analysis"
        assert subtype == "ranking_lookup"

        canonical, subtype = resolve_intent("category_breakdown")
        assert canonical == "product_analysis"
        assert subtype == "category_breakdown"

        canonical, subtype = resolve_intent("period_comparison")
        assert canonical == "comparison"
        assert subtype == "period_comparison"

        canonical, subtype = resolve_intent("inventory_lookup")
        assert canonical == "inventory_analysis"
        assert subtype == "inventory_lookup"

    def test_missing_tool_reconciliation(self):
        """Verify all legacy tool names resolve to active registered runtime tools."""
        registered_tool_names = {t["name"] for t in tool_registry.list_tools()}

        for legacy_tool, resolved_tool in LEGACY_TOOL_MAP.items():
            assert resolve_tool(legacy_tool) == resolved_tool
            assert resolved_tool in registered_tool_names, (
                f"Resolved tool '{resolved_tool}' is not registered in tool_registry!"
            )


class TestProviderCandidateConsistency:
    """Tests 7, 8, 9, 10: Candidate consistency across Gateway, Structured LLM, Jev, and Mock."""

    def test_gateway_candidate_consistency(self):
        """Verify DecisionGateway defaults to authoritative canonical intent candidates."""
        gateway = DecisionGateway(provider_name="mock")
        res = gateway.route_intent("What was revenue in August 2024?")
        assert res.status == DecisionStatus.SUCCESS
        assert res.decision in get_canonical_intent_ids()

    def test_mock_provider_consistency(self):
        """Verify Mock provider respects canonical intent candidates."""
        provider = MockDecisionProvider()
        req = DecisionRequest(
            task=DecisionTask.INTENT_ROUTING,
            input_text="What was our gross revenue last month?",
            candidate_options=get_canonical_intent_ids(),
        )
        res = provider.execute_decision(req)
        assert res.decision in get_canonical_intent_ids()

    def test_jev_provider_consistency(self):
        """Verify Jev provider defaults to and enforces canonical intent candidates."""
        mock_client = MagicMock()
        mock_answer = MagicMock()
        mock_answer.choice = "metric_lookup"
        mock_answer.confidence = 0.95
        mock_answer.probabilities = None

        mock_response = MagicMock()
        mock_response.answers = {"intent": mock_answer}
        mock_response.usage = None
        mock_client.system_one.return_value = mock_response

        provider = JevDecisionProvider(client=mock_client)
        req = DecisionRequest(
            task=DecisionTask.INTENT_ROUTING,
            input_text="What was our gross revenue last month?",
            # Leave candidate_options empty to test canonical default
        )
        res = provider.execute_decision(req)
        assert res.status == DecisionStatus.SUCCESS
        assert res.decision == "metric_lookup"

        # Check call arguments to system_one
        called_args = mock_client.system_one.call_args[1]
        criteria_keys = list(called_args["questions"]["intent"].criteria.keys())
        assert set(criteria_keys) == set(get_canonical_intent_ids())

    def test_structured_llm_candidate_consistency(self):
        """Verify Structured LLM provider operates with canonical intent candidates."""
        provider = StructuredLLMDecisionProvider(api_key="sk-test-key-mock")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps({"intent": "forecasting", "confidence": 0.94})))
        ]
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 120
        mock_client.chat.completions.create.return_value = mock_response
        provider._client = mock_client

        req = DecisionRequest(
            task=DecisionTask.INTENT_ROUTING,
            input_text="Forecast revenue for next 3 months",
            candidate_options=get_canonical_intent_ids(),
        )
        res = provider.execute_decision(req)
        assert res.status == DecisionStatus.SUCCESS
        assert res.decision == "forecasting"


class TestEvaluationDatasetIntegrityAndLeakage:
    """Tests 11, 13, 14: Dataset validity, exemplar compatibility, and zero leakage."""

    def test_evaluation_dataset_validity(self):
        """Verify all 57 evaluation cases have canonical expected intents and registered tools."""
        dataset_dir = os.path.join(os.path.dirname(__file__), "..", "..", "evaluation", "datasets")
        registered_tools = {t["name"] for t in tool_registry.list_tools()}
        canonical_intents = set(get_canonical_intent_ids())

        total_checked = 0
        for fname in ["golden_questions.json", "edge_cases.json", "adversarial_questions.json"]:
            path = os.path.join(dataset_dir, fname)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                cases = json.load(f)
            for c in cases:
                total_checked += 1
                exp_intent = c.get("expected_intent")
                if exp_intent:
                    assert exp_intent in canonical_intents, (
                        f"Case '{c.get('id')}' has non-canonical expected_intent: '{exp_intent}'"
                    )
                for t in c.get("expected_tools", []):
                    assert t in registered_tools, (
                        f"Case '{c.get('id')}' has unregistered tool: '{t}'"
                    )

        assert total_checked == 57

    def test_exemplar_canonical_compatibility(self):
        """Verify all 15 Phase 12C/13 exemplars use canonical intents."""
        canonical_intents = set(get_canonical_intent_ids())
        exemplars = get_intent_exemplars()
        assert len(exemplars) == 15
        for ex in exemplars:
            assert ex["target_intent"] in canonical_intents
            assert "target_subtype" in ex
            assert len(ex["target_subtype"]) > 0

    def test_zero_evaluation_leakage(self):
        """Verify programmatically that 0 evaluation cases leak into exemplars."""
        dataset_dir = os.path.join(os.path.dirname(__file__), "..", "..", "evaluation", "datasets")
        all_cases = []
        for fname in ["golden_questions.json", "edge_cases.json", "adversarial_questions.json"]:
            path = os.path.join(dataset_dir, fname)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    all_cases.extend(json.load(f))

        leak_result = verify_zero_evaluation_leakage(all_cases)
        assert leak_result["verified_clean"] is True
        assert len(leak_result["violations"]) == 0
