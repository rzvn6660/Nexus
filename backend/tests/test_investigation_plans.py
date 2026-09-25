"""Unit tests for Phase 6 Investigation Planning and plan formulation."""


from app.investigation.models import InvestigationType
from app.investigation.planner import InvestigationPlanner
from app.investigation.validators import InvestigationValidator


def test_revenue_decline_plan_formulation():
    """Verify formulation and validation of revenue decline investigation plan."""
    query = "Why did revenue decline in August 2024?"
    resolved_dates = {
        "date_from": "2024-08-01",
        "date_to": "2024-08-31",
    }
    plan, errors = InvestigationPlanner.plan(query, resolved_dates=resolved_dates)

    assert len(errors) == 0
    assert plan.investigation_type == InvestigationType.REVENUE_DECLINE
    assert len(plan.steps) >= 3
    assert plan.steps[0].tool == "get_financial_summary"
    assert plan.steps[1].tool == "run_variance_analysis"
    assert plan.steps[2].tool == "run_price_volume_mix"
    assert plan.baseline_dates["date_from"] is not None
    assert plan.baseline_dates["date_to"] is not None


def test_profit_decline_plan_formulation():
    """Verify formulation of profit decline investigation plan."""
    query = "Why did gross profit and net profit drop last month?"
    resolved_dates = {
        "date_from": "2024-08-01",
        "date_to": "2024-08-31",
        "comparison_date_from": "2024-07-01",
        "comparison_date_to": "2024-07-31",
    }
    plan, errors = InvestigationPlanner.plan(query, resolved_dates=resolved_dates)

    assert len(errors) == 0
    assert plan.investigation_type == InvestigationType.PROFIT_DECLINE
    assert any(s.tool == "get_expense_analytics" for s in plan.steps)
    assert any(s.tool == "run_price_volume_mix" for s in plan.steps)


def test_margin_change_plan_formulation():
    """Verify margin change diagnostic plan formulation."""
    query = "Why did our gross margin percentage compress?"
    resolved_dates = {"date_from": "2024-08-01", "date_to": "2024-08-31"}
    plan, errors = InvestigationPlanner.plan(query, resolved_dates=resolved_dates)

    assert len(errors) == 0
    assert plan.investigation_type == InvestigationType.MARGIN_CHANGE
    assert any(s.tool == "run_price_volume_mix" for s in plan.steps)
    assert any(s.tool == "get_category_breakdown" for s in plan.steps)


def test_inventory_issue_plan_formulation():
    """Verify inventory issue diagnostic plan formulation."""
    query = "Why are low stock levels and inventory turnover affecting operations?"
    resolved_dates = {"date_from": "2024-08-01", "date_to": "2024-08-31"}
    plan, errors = InvestigationPlanner.plan(query, resolved_dates=resolved_dates)

    assert len(errors) == 0
    assert plan.investigation_type == InvestigationType.INVENTORY_ISSUE
    assert any(s.tool == "get_inventory_overview" for s in plan.steps)
    assert any(s.tool == "get_inventory_turnover" for s in plan.steps)
    assert any(s.tool == "get_inventory_velocity" for s in plan.steps)


def test_customer_change_plan_formulation():
    """Verify customer repeat purchase diagnostic plan formulation."""
    query = "Why did repeat customer orders decline?"
    resolved_dates = {"date_from": "2024-08-01", "date_to": "2024-08-31"}
    plan, errors = InvestigationPlanner.plan(query, resolved_dates=resolved_dates)

    assert len(errors) == 0
    assert plan.investigation_type == InvestigationType.CUSTOMER_CHANGE
    assert any(s.tool == "get_repeat_purchase" for s in plan.steps)
    assert any(s.tool == "get_customer_segments" for s in plan.steps)


def test_plan_validation_rejects_unregistered_tool():
    """Verify plan validator catches invalid tools."""
    query = "Diagnose revenue drop"
    plan, _ = InvestigationPlanner.plan(query, resolved_dates={"date_from": "2024-08-01", "date_to": "2024-08-31"})
    
    # Inject an invalid tool
    plan.steps[0].tool = "arbitrary_sql_runner"
    is_valid, errors = InvestigationValidator.validate_plan(plan)

    assert is_valid is False
    assert any("not registered" in e for e in errors)
