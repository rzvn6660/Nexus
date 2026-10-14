"""OpenAI LLM Provider implementation for production execution."""

import json
from typing import Any

from app.agents.providers.base import BaseLLMProvider
from app.agents.providers.mock import MockLLMProvider
from app.agents.providers.prompts import TaskPromptBuilder, sanitize_fallback_reason
from app.agents.state.models import (
    AnalysisPlan,
    ExplanationLevel,
    GroundedExplanation,
    IntentCategory,
    IntentResult,
)
from app.core.config import settings


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI-compatible LLM provider implementing structured output workflows.
    Falls back to deterministic mock if no API key is configured.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.DEFAULT_LLM_MODEL
        self._fallback_mock = MockLLMProvider()

        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except Exception:  # noqa: BLE001
                self.client = None
        else:
            self.client = None

    def classify_intent(
        self, query: str, supported_intents: list[str]
    ) -> IntentResult:
        if not self.client:
            return self._fallback_mock.classify_intent(query, supported_intents)

        system_prompt = (
            "You are the intent classification module of NEXUS, an agentic business intelligence platform. "
            "Classify the user's business query into one of the supported intent categories: "
            f"{', '.join(supported_intents)}. "
            "Return valid JSON matching: {'category': '...', 'confidence': float, 'reasoning': '...'}"
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            return IntentResult.model_validate(data)
        except Exception:  # noqa: BLE001
            return self._fallback_mock.classify_intent(query, supported_intents)

    def create_plan(
        self,
        query: str,
        intent: IntentCategory,
        available_tools: list[dict[str, Any]],
        resolved_dates: dict[str, Any],
        semantic_context: dict[str, Any] | None = None,
    ) -> AnalysisPlan:
        from app.agents.providers.prompts import TaskPromptBuilder, sanitize_fallback_reason

        if not self.client:
            fallback_plan = self._fallback_mock.create_plan(
                query, intent, available_tools, resolved_dates, semantic_context=semantic_context
            )
            fallback_plan.is_fallback = True
            fallback_plan.fallback_reason = sanitize_fallback_reason("OPENAI_API_KEY is not configured")
            return fallback_plan

        system_prompt, user_content = TaskPromptBuilder.build_planning_prompt(
            query=query,
            intent=intent,
            available_tools=available_tools,
            resolved_dates=resolved_dates,
            semantic_context=semantic_context,
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            return AnalysisPlan.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            fallback_plan = self._fallback_mock.create_plan(
                query, intent, available_tools, resolved_dates, semantic_context=semantic_context
            )
            fallback_plan.is_fallback = True
            fallback_plan.fallback_reason = sanitize_fallback_reason(str(exc))
            return fallback_plan

    def explain_results_structured(
        self,
        query: str,
        plan: AnalysisPlan | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        explanation_level: ExplanationLevel = ExplanationLevel.MANAGER,
        business_context: str | None = None,
        semantic_context: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        rag_evidence: list[dict[str, Any]] | None = None,
    ) -> GroundedExplanation:
        if not self.client:
            return self._fallback_mock.explain_results_structured(
                query=query,
                plan=plan,
                tool_results=tool_results,
                evidence=evidence,
                explanation_level=explanation_level,
                business_context=business_context,
                semantic_context=semantic_context,
                warnings=warnings,
                rag_evidence=rag_evidence,
            )

        try:
            prompt = TaskPromptBuilder.build_explanation_prompt(
                query=query,
                plan=plan,
                tool_results=tool_results or [],
                evidence=evidence or [],
                explanation_level=explanation_level,
                business_context=business_context,
                semantic_context=semantic_context,
                warnings=warnings,
                rag_evidence=rag_evidence,
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt.system_prompt},
                    {"role": "user", "content": prompt.user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            return GroundedExplanation.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            fb = self._fallback_mock.explain_results_structured(
                query=query,
                plan=plan,
                tool_results=tool_results,
                evidence=evidence,
                explanation_level=explanation_level,
                business_context=business_context,
                semantic_context=semantic_context,
                warnings=warnings,
                rag_evidence=rag_evidence,
            )
            fb.is_fallback = True
            fb.fallback_reason = sanitize_fallback_reason(str(exc))
            return fb

    def explain_results(
        self,
        query: str,
        plan: AnalysisPlan | None,
        tool_results: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        explanation_level: ExplanationLevel,
        business_context: str | None = None,
    ) -> str:
        exp = self.explain_results_structured(
            query=query,
            plan=plan,
            tool_results=tool_results,
            evidence=evidence,
            explanation_level=explanation_level,
            business_context=business_context,
        )
        return exp.to_formatted_text(explanation_level)
