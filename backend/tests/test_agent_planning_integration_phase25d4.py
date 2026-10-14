"""Focused tests for NEXUS Phase 25D.4: Agent Planning Integration.

Verifies:
1. Canonical KPI and tool binding into structured analysis plan.
2. Ambiguous KPI prevents tool planning and triggers clarification.
3. Unavailable or unsupported KPI prevents tool planning and reports limitation.
4. Unsupported dimensions are stripped from tool arguments and recorded in plan warnings/limitations.
5. Unsupported filters are stripped from tool arguments and recorded in plan warnings/limitations.
6. Temporal context with tenant fiscal calendar propagates into plan context dates.
7. Evidence provenance (accounting rules, lineage) survives planning.
8. Tenant isolation in planning.
9. Backward compatibility of AnalysisPlan schema.
"""

from typing import Any

import pytest
from app.agents.nodes.planning import create_plan_node, validate_plan_node
from app.agents.state.models import AgentState, AnalysisPlan, IntentCategory
from app.models.base import Base
from app.models.tenant import Business, Organization, TenantSemanticModel
from app.services.tenant_semantic_service import TenantSemanticService
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def plan_db_session() -> Session:
    """In-memory SQLite database session for planning tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_planning_resolves_canonical_kpi_and_tools() -> None:
    """1. Valid canonical KPI binds directly to the approved deterministic tool and preserves provenance."""
    state: AgentState = {
        "user_query": "What was our net revenue last month?",
        "intent": {"category": IntentCategory.METRIC_LOOKUP.value},
        "resolved_dates": {"date_from": "2024-08-01", "date_to": "2024-08-31"},
        "semantic_context": {
            "canonical_name": "net_revenue",
            "analytics_tool": "get_financial_summary",
            "metric_field": "net_sales",
            "confidence": 1.0,
            "availability_status": "AVAILABLE",
            "is_supported": True,
            "is_ambiguous": False,
            "evidence_provenance": {
                "source_data": "sales",
                "accounting_rule_id": "REV-001",
                "policy_reference": "METRIC_DEFINITIONS: net_sales formula",
                "rule_name": "Net Revenue Determination",
            },
            "resolved_dimensions": [],
            "extracted_filters": {},
        },
        "limitations": [],
    }

    res = create_plan_node(state)
    assert res.get("analysis_plan") is not None
    plan = res["analysis_plan"]
    assert plan["confidence"] == 1.0
    assert len(plan["steps"]) >= 1
    assert plan["steps"][0]["tool_name"] == "get_financial_summary"
    assert plan["provenance"] is not None
    assert plan["provenance"]["accounting_rule_id"] == "REV-001"
    assert plan["provenance"]["policy_reference"] == "METRIC_DEFINITIONS: net_sales formula"

    # Validate plan passes validation
    val_state: AgentState = {
        "analysis_plan": plan,
        "semantic_context": state["semantic_context"],
        "errors": [],
    }
    val_res = validate_plan_node(val_state)
    assert len(val_res.get("errors", [])) == 0


def test_planning_aborts_on_ambiguous_kpi() -> None:
    """2. Ambiguous KPI prevents tool planning and returns needs_clarification."""
    state: AgentState = {
        "user_query": "Show me the margin",
        "intent": {"category": IntentCategory.METRIC_LOOKUP.value},
        "resolved_dates": {},
        "semantic_context": {
            "is_ambiguous": True,
            "clarification_prompt": "Are you asking about gross margin or net profit margin?",
            "confidence": 0.0,
            "is_supported": True,
            "canonical_name": None,
        },
        "limitations": [],
    }

    res = create_plan_node(state)
    assert res.get("analysis_plan") is None
    assert res.get("needs_clarification") is True
    assert "gross margin or net profit margin" in res.get("clarification_question", "")
    assert res.get("evidence_status") == "INSUFFICIENT"

    # Validate that validate_plan_node rejects an ambiguous plan
    bad_val_state: AgentState = {
        "analysis_plan": {
            "goal": "Test goal",
            "steps": [{"step_index": 0, "tool_name": "get_financial_summary", "purpose": "test", "arguments": {}}],
            "context_dates": {},
        },
        "semantic_context": state["semantic_context"],
        "errors": [],
    }
    val_res = validate_plan_node(bad_val_state)
    assert any("ambiguous" in err for err in val_res.get("errors", []))


def test_planning_aborts_on_unavailable_or_unsupported_kpi() -> None:
    """3. Unavailable metric (e.g. REQUIRES_COST_DATA) stops execution and explains limitation."""
    state: AgentState = {
        "user_query": "What is our gross margin?",
        "intent": {"category": IntentCategory.METRIC_LOOKUP.value},
        "resolved_dates": {},
        "semantic_context": {
            "canonical_name": "gross_margin",
            "availability_status": "REQUIRES_COST_DATA",
            "unsupported_message": "Gross Margin calculation requires cost data which is missing.",
            "is_supported": True,
            "is_ambiguous": False,
            "confidence": 0.0,
        },
        "limitations": [],
    }

    res = create_plan_node(state)
    assert res.get("analysis_plan") is None
    assert res.get("is_unsupported") is True
    assert "cost data which is missing" in res.get("unsupported_reason", "")
    assert res.get("evidence_status") == "INSUFFICIENT"

    # Test explicit unsupported metric (e.g. CLV)
    state_unsupp: AgentState = {
        "user_query": "What is our customer lifetime value?",
        "intent": {"category": IntentCategory.UNSUPPORTED.value},
        "resolved_dates": {},
        "semantic_context": {
            "is_supported": False,
            "unsupported_message": "Customer Lifetime Value (CLV) is not yet supported in NEXUS.",
            "confidence": 0.0,
            "canonical_name": None,
        },
        "limitations": [],
    }
    res_unsupp = create_plan_node(state_unsupp)
    assert res_unsupp.get("analysis_plan") is None
    assert res_unsupp.get("is_unsupported") is True
    assert "CLV" in res_unsupp.get("unsupported_reason", "")


def test_planning_strips_unsupported_dimensions_and_records_warning() -> None:
    """4. Unsupported dimensions are omitted from tool arguments and documented in plan warnings."""
    state: AgentState = {
        "user_query": "inventory turnover by customer segment",
        "intent": {"category": IntentCategory.INVENTORY_ANALYSIS.value},
        "resolved_dates": {"date_from": "2024-01-01", "date_to": "2024-03-31"},
        "semantic_context": {
            "canonical_name": "inventory_turnover",
            "analytics_tool": "get_inventory_turnover",
            "confidence": 0.80,
            "availability_status": "AVAILABLE",
            "is_supported": True,
            "is_ambiguous": False,
            "resolved_dimensions": [],
            "unsupported_dimensions": ["customer_segment"],
            "unsupported_message": "Requested dimension(s) ['customer_segment'] are not supported for metric 'inventory_turnover'.",
        },
        "limitations": [],
    }

    res = create_plan_node(state)
    assert res.get("analysis_plan") is not None
    plan = res["analysis_plan"]
    assert plan["confidence"] == 0.80
    assert any("customer_segment" in w for w in plan["warnings"])
    assert any("customer_segment" in lim for lim in res["limitations"])

    # Ensure customer_segment is not passed to tool arguments
    for step in plan["steps"]:
        assert "customer_segment" not in step.get("arguments", {})


def test_planning_strips_unsupported_filters_and_records_warning() -> None:
    """5. Unsupported filters (e.g. warehouse on net_revenue) are stripped from tool arguments."""
    state: AgentState = {
        "user_query": "revenue for Main Warehouse",
        "intent": {"category": IntentCategory.METRIC_LOOKUP.value},
        "resolved_dates": {"date_from": "2024-01-01", "date_to": "2024-01-31"},
        "semantic_context": {
            "canonical_name": "net_revenue",
            "analytics_tool": "get_financial_summary",
            "confidence": 0.95,
            "availability_status": "AVAILABLE",
            "is_supported": True,
            "is_ambiguous": False,
            "extracted_filters": {},
            "unsupported_filters": {"warehouse": "Main Warehouse"},
            "unsupported_message": "Requested filter(s) ['warehouse'] are not supported for metric 'net_revenue'.",
        },
        "limitations": [],
    }

    res = create_plan_node(state)
    assert res.get("analysis_plan") is not None
    plan = res["analysis_plan"]
    assert any("warehouse" in w for w in plan["warnings"])
    assert any("warehouse" in lim for lim in res["limitations"])

    # Ensure warehouse filter was stripped from step arguments
    for step in plan["steps"]:
        assert "warehouse" not in step.get("arguments", {})

    # Validation should reject plan if an unsupported filter is illegally injected into arguments
    illegal_plan_state: AgentState = {
        "analysis_plan": {
            "goal": "Illegal query",
            "steps": [
                {
                    "step_index": 0,
                    "tool_name": "get_financial_summary",
                    "purpose": "Test",
                    "arguments": {"warehouse": "Main Warehouse"},
                }
            ],
            "context_dates": {},
        },
        "semantic_context": state["semantic_context"],
        "errors": [],
    }
    val_res = validate_plan_node(illegal_plan_state)
    assert any("unsupported filter 'warehouse'" in err for err in val_res.get("errors", []))


def test_planning_preserves_temporal_context_and_fiscal_calendar() -> None:
    """6. Tenant fiscal calendar and parsed date bounds propagate to plan context dates."""
    state: AgentState = {
        "user_query": "revenue this fiscal year",
        "intent": {"category": IntentCategory.METRIC_LOOKUP.value},
        "resolved_dates": {},
        "semantic_context": {
            "canonical_name": "net_revenue",
            "analytics_tool": "get_financial_summary",
            "confidence": 1.0,
            "availability_status": "AVAILABLE",
            "is_supported": True,
            "is_ambiguous": False,
            "temporal_context": {
                "date_from": "2025-07-01",
                "date_to": "2026-03-15",
                "comparison_date_from": "2024-07-01",
                "comparison_date_to": "2025-03-15",
                "granularity": "quarterly",
                "fiscal_calendar": {
                    "fiscal_year_start_month": 7,
                    "timezone": "America/New_York",
                    "currency": "USD",
                },
            },
        },
        "limitations": [],
    }

    res = create_plan_node(state)
    plan = res["analysis_plan"]
    assert plan["context_dates"]["date_from"] == "2025-07-01"
    assert plan["context_dates"]["date_to"] == "2026-03-15"
    assert plan["context_dates"]["fiscal_calendar"]["fiscal_year_start_month"] == 7
    assert plan["context_dates"]["fiscal_calendar"]["timezone"] == "America/New_York"
    assert plan["steps"][0]["arguments"]["date_from"] == "2025-07-01"


def test_planning_cross_tenant_isolation(plan_db_session: Session) -> None:
    """7. Tenant custom synonyms and calendar scope strictly isolated during planning."""
    # Tenant A (July fiscal year, custom synonym "ops_revenue" -> "net_revenue")
    org_a = Organization(id="org_plan_a", name="Org A", slug="org-plan-a")
    biz_a = Business(
        id="biz_plan_a",
        organization_id=org_a.id,
        name="Business A",
        industry="Retail",
        timezone="America/New_York",
        currency="USD",
        fiscal_year_start=7,
    )
    model_a = TenantSemanticModel(
        id="model_plan_a",
        organization_id=org_a.id,
        business_id=biz_a.id,
        version=1,
        status="ACTIVE",
        metrics_json={"net_revenue": {"display_name": "Net Revenue", "status": "AVAILABLE"}},
        synonyms_json={"ops_revenue": "net_revenue"},
    )
    plan_db_session.add_all([org_a, biz_a, model_a])
    plan_db_session.commit()

    # Tenant B (January fiscal year, no custom synonym)
    org_b = Organization(id="org_plan_b", name="Org B", slug="org-plan-b")
    biz_b = Business(
        id="biz_plan_b",
        organization_id=org_b.id,
        name="Business B",
        industry="Tech",
        timezone="UTC",
        currency="EUR",
        fiscal_year_start=1,
    )
    model_b = TenantSemanticModel(
        id="model_plan_b",
        organization_id=org_b.id,
        business_id=biz_b.id,
        version=1,
        status="ACTIVE",
        metrics_json={"net_revenue": {"display_name": "Net Revenue", "status": "AVAILABLE"}},
        synonyms_json={},
    )
    plan_db_session.add_all([org_b, biz_b, model_b])
    plan_db_session.commit()

    # Resolve for Tenant A
    res_a = TenantSemanticService.resolve_query_with_tenant_context(
        query="ops_revenue this fiscal year",
        business_id=biz_a.id,
        db=plan_db_session,
    )
    assert res_a.canonical_name == "net_revenue"

    state_a: AgentState = {
        "user_query": "ops_revenue this fiscal year",
        "business_id": biz_a.id,
        "intent": {"category": IntentCategory.METRIC_LOOKUP.value},
        "resolved_dates": {},
        "semantic_context": res_a.model_dump(),
        "limitations": [],
    }
    plan_a = create_plan_node(state_a)["analysis_plan"]
    assert plan_a["context_dates"]["fiscal_calendar"]["fiscal_year_start_month"] == 7
    assert plan_a["steps"][0]["tool_name"] == "get_financial_summary"

    # Resolve for Tenant B: ops_revenue is unknown
    res_b = TenantSemanticService.resolve_query_with_tenant_context(
        query="ops_revenue this fiscal year",
        business_id=biz_b.id,
        db=plan_db_session,
    )
    # Tenant B does NOT resolve custom synonym ops_revenue
    assert res_b.matched_synonym != "ops_revenue"


def test_analysis_plan_backward_compatibility() -> None:
    """8. Legacy AnalysisPlan instances validate cleanly with new default attributes."""
    legacy_payload: dict[str, Any] = {
        "goal": "Legacy Analysis Goal",
        "steps": [
            {
                "step_index": 0,
                "tool_name": "get_financial_summary",
                "purpose": "Legacy step",
                "arguments": {"date_from": "2024-01-01", "date_to": "2024-01-31"},
            }
        ],
        "context_dates": {"date_from": "2024-01-01", "date_to": "2024-01-31"},
    }

    plan = AnalysisPlan.model_validate(legacy_payload)
    assert plan.goal == "Legacy Analysis Goal"
    assert len(plan.steps) == 1
    assert plan.confidence == 1.0
    assert plan.warnings == []
    assert plan.semantic_context is None
    assert plan.provenance is None


def test_execution_boundary_routing_and_rejection() -> None:
    """9. Complete execution boundary verifies invalid/unsupported/ambiguous plans cannot reach execute_tool."""
    from app.agents.graph.workflow import route_after_plan_validation
    from app.agents.nodes.execution import execute_tool_node

    # Case A: Plan validation fails on unsupported metric
    state_unsupp: AgentState = {
        "user_query": "What is our unsupported kpi?",
        "intent": {"category": IntentCategory.UNSUPPORTED.value},
        "resolved_dates": {},
        "semantic_context": {
            "is_supported": False,
            "unsupported_message": "Unsupported metric",
            "canonical_name": None,
        },
        "analysis_plan": {
            "goal": "Illegal query",
            "steps": [{"step_index": 0, "tool_name": "get_financial_summary", "purpose": "test", "arguments": {}}],
            "context_dates": {},
        },
        "errors": [],
    }
    val_res = validate_plan_node(state_unsupp)
    assert val_res.get("evidence_status") == "ERROR"
    assert any("unsupported metric" in err for err in val_res.get("errors", []))

    # Boundary check: route_after_plan_validation must route to generate_explanation, never execute_tool
    next_node = route_after_plan_validation({**state_unsupp, **val_res})
    assert next_node == "generate_explanation"

    # Case B: Plan validation fails on unsupported dimension argument
    state_bad_dim: AgentState = {
        "user_query": "variance by warehouse",
        "intent": {"category": IntentCategory.DIAGNOSTIC_ANALYSIS.value},
        "resolved_dates": {},
        "semantic_context": {
            "canonical_name": "variance",
            "is_supported": True,
            "unsupported_dimensions": ["warehouse"],
        },
        "analysis_plan": {
            "goal": "Variance by warehouse",
            "steps": [
                {
                    "step_index": 0,
                    "tool_name": "run_variance_analysis",
                    "purpose": "Variance analysis",
                    "arguments": {"dimension": "warehouse"},
                }
            ],
            "context_dates": {},
        },
        "errors": [],
    }
    val_dim_res = validate_plan_node(state_bad_dim)
    assert val_dim_res.get("evidence_status") == "ERROR"
    assert any("unsupported dimension" in err for err in val_dim_res.get("errors", []))
    assert route_after_plan_validation({**state_bad_dim, **val_dim_res}) == "generate_explanation"

    # Case C: execute_tool_node safety guard when plan has no steps
    empty_plan_state: AgentState = {
        "analysis_plan": None,
        "current_step_index": 0,
        "tool_calls": [],
        "tool_results": [],
    }
    exec_res = execute_tool_node(empty_plan_state)
    assert len(empty_plan_state["tool_calls"]) == 0
    assert len(empty_plan_state["tool_results"]) == 0
    assert exec_res.get("evidence_status") == "SUFFICIENT"


def test_provenance_and_confidence_cannot_be_forged_by_provider() -> None:
    """10. Plan confidence and provenance are strictly bound from verified semantic context, not provider output."""
    from app.agents.providers.mock import MockLLMProvider
    from app.agents.state.models import PlanStep

    # Even if provider produced a plan with forged/unverified values
    fake_plan = AnalysisPlan(
        goal="Test goal",
        steps=[PlanStep(step_index=0, tool_name="get_financial_summary", purpose="Test", arguments={})],
        context_dates={},
        confidence=0.99,  # Forged confidence
        provenance={"rule": "FORGED_RULE_999"},  # Forged provenance
    )

    class ForgedProvider(MockLLMProvider):
        def create_plan(self, *args: Any, **kwargs: Any) -> AnalysisPlan:
            return fake_plan

    import app.agents.nodes.planning as planning_mod
    original_get_provider = planning_mod.get_llm_provider
    planning_mod.get_llm_provider = lambda: ForgedProvider()

    try:
        verified_provenance = {
            "source_data": "orders",
            "accounting_rule_id": "REV-001",
            "policy_reference": "METRIC_DEFINITIONS: net_sales formula",
            "rule_name": "Net Revenue Determination",
        }
        state: AgentState = {
            "user_query": "What was our net revenue?",
            "intent": {"category": IntentCategory.METRIC_LOOKUP.value},
            "resolved_dates": {},
            "semantic_context": {
                "canonical_name": "net_revenue",
                "analytics_tool": "get_financial_summary",
                "confidence": 0.75,  # Verified lower confidence
                "availability_status": "AVAILABLE",
                "is_supported": True,
                "is_ambiguous": False,
                "evidence_provenance": verified_provenance,
            },
            "limitations": [],
        }

        res = create_plan_node(state)
        plan = res["analysis_plan"]
        # Must match verified semantic context, not forged provider values
        assert plan["confidence"] == 0.75
        assert plan["provenance"] == verified_provenance
        assert plan["provenance"]["accounting_rule_id"] == "REV-001"
    finally:
        planning_mod.get_llm_provider = original_get_provider


def test_provider_backward_compatibility_and_fallback() -> None:
    """11. Provider create_plan signatures support both semantic_context and legacy invocations."""
    from app.agents.providers.interface import NexusLLMInterface
    from app.agents.providers.live_adapter import OpenAICompatibleLiveProvider
    from app.agents.providers.mock import MockLLMProvider

    tools = [{"name": "get_financial_summary", "description": "Scorecard"}]
    dates = {"date_from": "2024-01-01", "date_to": "2024-01-31"}

    # Mock provider: legacy call without semantic_context
    mock_prov = MockLLMProvider()
    p_legacy = mock_prov.create_plan("revenue", IntentCategory.METRIC_LOOKUP, tools, dates)
    assert p_legacy is not None
    assert len(p_legacy.steps) >= 1

    # Mock provider: call with semantic_context
    sem_ctx = {"canonical_name": "repeat_purchase_rate", "analytics_tool": "get_repeat_purchase", "confidence": 1.0}
    p_sem = mock_prov.create_plan("repeat buyers", IntentCategory.CUSTOMER_ANALYSIS, tools, dates, semantic_context=sem_ctx)
    assert p_sem.steps[0].tool_name == "get_repeat_purchase"
    assert p_sem.confidence == 1.0

    # NexusLLMInterface: call with semantic_context
    interface = NexusLLMInterface()
    p_iface = interface.create_plan("inventory turnover", IntentCategory.INVENTORY_ANALYSIS, tools, dates, semantic_context={"canonical_name": "inventory_turnover", "analytics_tool": "get_inventory_turnover", "confidence": 0.88})
    assert p_iface is not None
    assert p_iface.steps[0].tool_name == "get_inventory_turnover"

    # OpenAICompatibleLiveProvider fallback with semantic_context
    live = OpenAICompatibleLiveProvider(provider_name="groq", model_name="llama3-70b", api_key=None, base_url=None)
    p_live = live.create_plan("expenses", IntentCategory.EXPENSE_ANALYSIS, tools, dates, semantic_context={"canonical_name": "operating_expenses", "analytics_tool": "get_expense_analytics", "confidence": 0.92})
    assert p_live is not None
    assert p_live.steps[0].tool_name == "get_expense_analytics"

