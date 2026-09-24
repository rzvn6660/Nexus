"""Security tests and edge case handling for the NEXUS agentic layer."""

from app.agents.nodes.execution import execute_tool_node
from app.agents.service import NexusAgentService
from app.agents.state.models import AgentState
from app.agents.tools.registry import tool_registry
from sqlalchemy.orm import Session


def test_security_sql_injection_attempt_in_query(multi_period_db: Session) -> None:
    service = NexusAgentService(multi_period_db)
    # Attacker attempts SQL injection via query string
    malicious_query = "What was revenue'; DROP TABLE sales; --"
    response = service.run_analysis(malicious_query)

    assert response.status == "completed"
    # Verify sales table is completely intact and accessible
    res = tool_registry.execute("get_financial_summary", multi_period_db, {})
    assert res.status == "success"
    assert "net_sales" in res.result


def test_security_unregistered_tool_cannot_execute(multi_period_db: Session) -> None:
    res = tool_registry.execute("execute_bash_command", multi_period_db, {"command": "rm -rf /"})
    assert res.status == "error"
    assert "Security violation" in res.error_message


def test_security_arbitrary_code_injection_rejected(multi_period_db: Session) -> None:
    # Attempting to pass code in arguments to an existing tool
    res = tool_registry.execute(
        "get_financial_summary",
        multi_period_db,
        {"customer_ids": ["__import__('os').system('echo pwned')"]},
    )
    # Pydantic validation fails because customer_ids must be integers
    assert res.status == "error"
    assert "validation error" in res.error_message.lower()


def test_iteration_limit_enforced() -> None:
    state: AgentState = {
        "analysis_plan": {
            "goal": "Loop test",
            "steps": [
                {"step_index": 0, "tool_name": "get_financial_summary", "purpose": "Step 0", "arguments": {}},
            ],
            "context_dates": {},
        },
        "iteration_count": 5,
        "max_iterations": 5,
        "current_step_index": 0,
        "errors": [],
    }
    result = execute_tool_node(state)
    assert result.get("iteration_count") == 6
    assert any("Maximum iteration limit" in err for err in result.get("errors", []))
