"""Structured LLM Decision Provider adapting existing OpenAI/LLM capabilities."""

import json
import time
from typing import Any

from app.core.config import settings
from app.decisions.base import BaseDecisionProvider
from app.decisions.errors import (
    DecisionProviderUnavailableError,
    DecisionTimeoutError,
    MalformedDecisionResponseError,
)
from app.decisions.models import (
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionTask,
    DecisionTelemetry,
)

# Standard OpenAI pricing estimates per 1M tokens (USD)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # model: (input_cost_per_1m, output_cost_per_1m)
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
}


class StructuredLLMDecisionProvider(BaseDecisionProvider):
    """
    Baseline structured decision provider wrapping production OpenAI/LLM calls.
    
    SAFETY INVARIANT:
    Under NO circumstances will this provider silently switch to a mock response
    if a live call fails. Live errors must raise DecisionProviderUnavailableError or
    DecisionTimeoutError, or return an explicitly marked FAILED result.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.DEFAULT_LLM_MODEL
        self._client = None

        if self.api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except Exception as e:
                self._client = None
                self._init_error = str(e)
        else:
            self._init_error = "OPENAI_API_KEY is not configured"

    @property
    def provider_name(self) -> str:
        return "structured_llm"

    def health_check(self) -> bool:
        return self._client is not None

    def execute_decision(self, request: DecisionRequest) -> DecisionResult:
        if not self._client:
            raise DecisionProviderUnavailableError(
                f"StructuredLLMDecisionProvider is unavailable: {getattr(self, '_init_error', 'Missing credentials')}"
            )

        start_time = time.perf_counter()
        task_str = request.task.value if isinstance(request.task, DecisionTask) else str(request.task)

        # Build task-specific structured prompt
        system_prompt, user_content = self._build_prompts(request, task_str)

        timeout = float(request.constraints.get("timeout_seconds", getattr(settings, "DECISION_TIMEOUT_SECONDS", 10.0)))

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout=timeout,
            )
        except Exception as ex:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            ex_str = str(ex).lower()
            if "timeout" in ex_str or "timed out" in ex_str:
                raise DecisionTimeoutError(f"Structured LLM decision timed out after {elapsed_ms}ms: {ex}") from ex
            raise DecisionProviderUnavailableError(f"Live LLM provider error during decision: {ex}") from ex

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        raw_content = response.choices[0].message.content or "{}"

        try:
            parsed_json = json.loads(raw_content)
        except json.JSONDecodeError as jde:
            raise MalformedDecisionResponseError(f"LLM returned non-JSON payload: {jde}") from jde

        # Extract telemetry
        usage = getattr(response, "usage", None)
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        total_tokens = usage.total_tokens if usage else None

        estimated_cost = self._calculate_cost(prompt_tokens, completion_tokens)

        telemetry = DecisionTelemetry(
            provider=self.provider_name,
            model=self.model,
            latency_ms=elapsed_ms,
            tokens_used=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost,
        )

        # Parse selected decision and rationale
        decision_val = (
            parsed_json.get("decision")
            or parsed_json.get("category")
            or parsed_json.get("selected")
            or parsed_json.get("intent")
        )
        rationale_val = parsed_json.get("rationale") or parsed_json.get("reasoning")
        confidence_val = parsed_json.get("confidence")

        # Ensure confidence is float if present, otherwise None (do not invent fake confidence)
        clean_confidence = None
        if confidence_val is not None:
            try:
                clean_confidence = float(confidence_val)
                if not (0.0 <= clean_confidence <= 1.0):
                    clean_confidence = None
            except (ValueError, TypeError):
                clean_confidence = None

        return DecisionResult(
            task=task_str,
            status=DecisionStatus.SUCCESS,
            decision=str(decision_val) if decision_val is not None else None,
            structured_output=parsed_json,
            rationale=rationale_val,
            confidence=clean_confidence,
            telemetry=telemetry,
            is_fallback=False,
        )

    def _build_prompts(self, request: DecisionRequest, task_str: str) -> tuple[str, str]:
        candidates_str = ", ".join(f"'{c}'" for c in request.candidate_options) if request.candidate_options else "None specified"

        system_prompt = (
            "You are the structured Decision Gateway for NEXUS, an agentic business intelligence platform. "
            f"Your current task is: '{task_str}'. "
            "You must evaluate the input and constraints, and return ONLY a valid JSON object. "
            "Never generate conversational text or markdown codeblocks outside JSON. "
        )

        if request.candidate_options:
            system_prompt += f"Allowed candidate decisions: [{candidates_str}]. "
            system_prompt += "Your JSON must include a 'decision' field containing exactly one of the allowed candidates. "

        system_prompt += "JSON structure: {'decision': str, 'confidence': float (between 0.0 and 1.0 if confident, or null), 'reasoning': str, ...}"

        user_payload: dict[str, Any] = {
            "task": task_str,
            "input_text": request.input_text,
            "candidate_options": request.candidate_options,
        }
        if request.context:
            user_payload["context"] = request.context
        if request.constraints:
            user_payload["constraints"] = request.constraints

        return system_prompt, json.dumps(user_payload)

    def _calculate_cost(self, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
        if prompt_tokens is None or completion_tokens is None:
            return None
        pricing = MODEL_PRICING.get(self.model)
        if not pricing:
            return None
        in_rate, out_rate = pricing
        cost = (prompt_tokens / 1_000_000 * in_rate) + (completion_tokens / 1_000_000 * out_rate)
        return round(cost, 6)
