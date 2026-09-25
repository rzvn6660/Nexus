"""Regression tests for Phase 11 correctness fixes (far-future dates & ambiguous queries)."""

import pytest
from sqlalchemy.orm import Session

from app.agents.service import NexusAgentService
from app.agents.tools.date_interpreter import DateInterpreter


def test_far_future_date_temporal_boundary_notice(multi_period_db: Session):
    """
    Evaluation Fix #1:
    Far-future dates (e.g. December 2099) must produce an explicit semantic/date-boundary
    notice instead of silently returning an empty $0.00 result.
    """
    service = NexusAgentService(multi_period_db)
    response = service.run_analysis("What was our revenue in December 2099?")

    assert response.status == "completed"
    assert response.intent == "metric_lookup"
    # Verify the final answer contains the temporal boundary notice
    assert "Temporal Boundary Notice" in response.answer or "beyond the historical" in response.answer.lower()
    assert "2099" in response.answer


def test_ambiguous_breakdown_requests_clarification(multi_period_db: Session):
    """
    Evaluation Fix #2:
    Ambiguous requests such as 'Give me a breakdown' must request clarification
    when required dimensions/metrics are missing.
    """
    service = NexusAgentService(multi_period_db)

    # 1. "Give me a breakdown"
    resp1 = service.run_analysis("Give me a breakdown")
    assert resp1.status == "clarification_needed"
    assert resp1.needs_clarification is True
    assert resp1.clarification_prompt is not None
    assert "metric" in resp1.clarification_prompt.lower()
    assert "dimension" in resp1.clarification_prompt.lower()

    # 2. "Show me a breakdown"
    resp2 = service.run_analysis("Show me a breakdown")
    assert resp2.status == "clarification_needed"
    assert resp2.needs_clarification is True

    # 3. Explicit breakdown should succeed without clarification
    resp3 = service.run_analysis("Break down revenue by category")
    assert resp3.status == "completed"
    assert resp3.needs_clarification is False
