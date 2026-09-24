"""OpenAI LLM Provider implementation for production execution."""

import json
from typing import Any

from app.agents.providers.base import BaseLLMProvider
from app.agents.providers.mock import MockLLMProvider
from app.agents.state.models import (
    AnalysisPlan,
    ExplanationLevel,
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
            except Exception:
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
        except Exception:
            return self._fallback_mock.classify_intent(query, supported_intents)

    def create_plan(
        self,
        query: str,
        intent: IntentCategory,
        available_tools: list[dict[str, Any]],
        resolved_dates: dict[str, Any],
    ) -> AnalysisPlan:
        if not self.client:
            return self._fallback_mock.create_plan(query, intent, available_tools, resolved_dates)

        system_prompt = (
            "You are the planning engine of NEXUS. Create a structured analytical plan. "
            "You MUST ONLY select from the available deterministic tools: "
            f"{', '.join(t['name'] for t in available_tools)}. "
            "DO NOT invent tools or perform mathematical calculations yourself. "
            "Return valid JSON matching the AnalysisPlan schema: "
            "{'goal': str, 'steps': [{'step_index': int, 'tool_name': str, 'purpose': str, 'arguments': dict}], 'context_dates': dict}"
        )
        user_content = json.dumps({
            "query": query,
            "intent": intent.value,
            "resolved_dates": resolved_dates,
        })
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
        except Exception:
            return self._fallback_mock.create_plan(query, intent, available_tools, resolved_dates)

    def explain_results(
        self,
        query: str,
        plan: AnalysisPlan | None,
        tool_results: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        explanation_level: ExplanationLevel,
    ) -> str:
        if not self.client:
            return self._fallback_mock.explain_results(query, plan, tool_results, evidence, explanation_level)

        system_prompt = (
            "You are the explanation synthesizer of NEXUS. "
            "CRITICAL RULE: You are an explainer, NOT a calculator. Never invent numbers. "
            "Ground every figure strictly in the provided deterministic tool results and evidence. "
            "Tone must be professional, objective, and clear. Emphasize that variance/correlation indicates "
            "association rather than established causality. "
            f"Tailor the depth to explanation level: {explanation_level.value}."
        )
        user_content = json.dumps({
            "query": query,
            "tool_results": tool_results,
            "evidence": evidence,
            "explanation_level": explanation_level.value,
        })
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
            )
            return response.choices[0].message.content or "No explanation generated."
        except Exception:
            return self._fallback_mock.explain_results(query, plan, tool_results, evidence, explanation_level)
