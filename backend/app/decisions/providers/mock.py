"""Deterministic Mock Decision Provider for testing and offline execution."""

import time
from typing import Any
from app.decisions.base import BaseDecisionProvider
from app.decisions.errors import DecisionProviderUnavailableError, DecisionTimeoutError
from app.decisions.models import (
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionTask,
    DecisionTelemetry,
)


class MockDecisionProvider(BaseDecisionProvider):
    """
    Deterministic mock provider for unit testing and offline development.
    
    Guarantees zero external network or API calls. Supports explicit mock configuration
    for simulating pre-canned responses, network timeouts, and provider errors.
    """

    def __init__(self) -> None:
        self._configured_responses: dict[str, DecisionResult] = {}
        self._simulated_errors: dict[str, str] = {}
        self._simulated_timeouts: set[str] = set()

    @property
    def provider_name(self) -> str:
        return "mock"

    def health_check(self) -> bool:
        return True

    def set_response(self, task: DecisionTask | str, result: DecisionResult) -> None:
        """Configure a predetermined DecisionResult for a given task."""
        key = task.value if isinstance(task, DecisionTask) else str(task)
        self._configured_responses[key] = result

    def set_error(self, task: DecisionTask | str, error_message: str) -> None:
        """Configure a simulated provider failure for a given task."""
        key = task.value if isinstance(task, DecisionTask) else str(task)
        self._simulated_errors[key] = error_message

    def set_timeout(self, task: DecisionTask | str) -> None:
        """Configure a simulated timeout for a given task."""
        key = task.value if isinstance(task, DecisionTask) else str(task)
        self._simulated_timeouts.add(key)

    def clear_overrides(self) -> None:
        """Clear all configured responses and failure simulations."""
        self._configured_responses.clear()
        self._simulated_errors.clear()
        self._simulated_timeouts.clear()

    def execute_decision(self, request: DecisionRequest) -> DecisionResult:
        start_time = time.perf_counter()
        task_key = request.task.value if isinstance(request.task, DecisionTask) else str(request.task)

        # 1. Check simulated timeout
        if task_key in self._simulated_timeouts or "all" in self._simulated_timeouts:
            raise DecisionTimeoutError(f"Mock decision provider timed out on task '{task_key}'")

        # 2. Check simulated error
        if task_key in self._simulated_errors:
            raise DecisionProviderUnavailableError(self._simulated_errors[task_key])
        if "all" in self._simulated_errors:
            raise DecisionProviderUnavailableError(self._simulated_errors["all"])

        # 3. Check configured response
        if task_key in self._configured_responses:
            res = self._configured_responses[task_key].model_copy(deep=True)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            res.telemetry.latency_ms = elapsed_ms
            return res

        # 4. Default deterministic logic based on task
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        telemetry = DecisionTelemetry(
            provider="mock",
            model="mock-deterministic-v1",
            latency_ms=elapsed_ms,
            tokens_used=0,
            prompt_tokens=0,
            completion_tokens=0,
            estimated_cost_usd=0.0,
        )

        return self._dispatch_default_mock(request, telemetry)

    def _dispatch_default_mock(self, request: DecisionRequest, telemetry: DecisionTelemetry) -> DecisionResult:
        task_str = request.task.value if isinstance(request.task, DecisionTask) else str(request.task)
        text_lower = request.input_text.lower().strip()

        if task_str == DecisionTask.INTENT_ROUTING.value:
            # Delegate to existing MockLLMProvider to guarantee complete behavioral equivalence
            from app.agents.providers.mock import MockLLMProvider
            mock_llm = MockLLMProvider()
            candidate_options = request.candidate_options or []
            intent_result = mock_llm.classify_intent(request.input_text, candidate_options)
            chosen_intent = intent_result.category.value

            return DecisionResult(
                task=task_str,
                status=DecisionStatus.SUCCESS,
                decision=chosen_intent,
                structured_output={
                    "category": chosen_intent,
                    "confidence": intent_result.confidence,
                    "reasoning": intent_result.reasoning,
                },
                rationale=intent_result.reasoning,
                confidence=intent_result.confidence,
                telemetry=telemetry,
            )

        elif task_str == DecisionTask.TOOL_SELECTION.value:
            selected_tool = request.candidate_options[0] if request.candidate_options else "get_financial_summary"
            return DecisionResult(
                task=task_str,
                status=DecisionStatus.SUCCESS,
                decision=selected_tool,
                structured_output={"selected_tools": [selected_tool]},
                rationale="Default mock tool selection",
                confidence=None,
                telemetry=telemetry,
            )

        elif task_str == DecisionTask.EVIDENCE_SUFFICIENCY.value:
            # Check context tool_results
            results = request.context.get("tool_results", [])
            has_success = any(r.get("status") == "success" for r in results) if isinstance(results, list) else False
            status_val = "SUFFICIENT" if has_success else "INSUFFICIENT"
            return DecisionResult(
                task=task_str,
                status=DecisionStatus.SUCCESS,
                decision=status_val,
                structured_output={"sufficiency": status_val, "is_sufficient": has_success},
                rationale="Evaluated presence of successful deterministic tool outputs",
                confidence=None,
                telemetry=telemetry,
            )

        elif task_str == DecisionTask.RISK_GATING.value:
            # Low risk by default
            return DecisionResult(
                task=task_str,
                status=DecisionStatus.SUCCESS,
                decision="LOW",
                structured_output={"risk_level": "LOW", "requires_immediate_escalation": False},
                rationale="Standard analytical recommendation does not mutate production operational state",
                confidence=None,
                telemetry=telemetry,
            )

        elif task_str == DecisionTask.RAG_RERANKING.value:
            chunks = request.context.get("candidates", [])
            top_k = int(request.constraints.get("top_k", 3))
            ranked = chunks[:top_k] if isinstance(chunks, list) else []
            return DecisionResult(
                task=task_str,
                status=DecisionStatus.SUCCESS,
                decision="ranked",
                structured_output={"ranked_items": ranked},
                rationale="Mock preserved rank order",
                confidence=None,
                telemetry=telemetry,
            )

        # Generic fallback
        chosen = request.candidate_options[0] if request.candidate_options else "default"
        return DecisionResult(
            task=task_str,
            status=DecisionStatus.SUCCESS,
            decision=chosen,
            structured_output={"value": chosen},
            rationale="Generic mock decision",
            confidence=None,
            telemetry=telemetry,
        )
