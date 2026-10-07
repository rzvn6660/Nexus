"""Deterministic Calculation Guard for NEXUS Intelligence 2.0.

Enforces the core NEXUS architectural invariant:
- Deterministic calculations → SQL, Python analytics engine, statistics, ML.
- LLM → Language comprehension, intent understanding, tool planning, ambiguity resolution,
  evidence interpretation, grounded explanations.
- Never use an LLM to calculate financial or numerical truth independently.
"""

import logging
import re
from typing import Any

from app.agents.providers.models import (
    DeterministicInvariantViolationError,
    LLMRequest,
    LLMResponse,
)

logger = logging.getLogger(__name__)


class DeterministicCalculationGuard:
    """
    Guard that verifies requests and responses adhere to the deterministic calculation boundary.
    """

    # Patterns indicating an attempt to use the LLM as a raw arithmetic calculator
    PROHIBITED_ARITHMETIC_PROMPTS = [
        re.compile(r"\bcalculate\s+(?:the\s+)?(?:sum|difference|product|division|variance|stddev|standard\s+deviation)\s+of\b", re.IGNORECASE),
        re.compile(r"\bcompute\s+(?:the\s+)?(?:math|arithmetic|formula|sum)\s+(?:directly|manually)\b", re.IGNORECASE),
        re.compile(r"\bdo\s+not\s+use\s+(?:tools|sql|analytics)\b", re.IGNORECASE),
        re.compile(r"\bcalculate\s+[\d\.,\s\+\-\*\/\^\(\)]+\s*=", re.IGNORECASE),
    ]

    # Patterns indicating LLM invented fake zero costs when costs are missing
    ZERO_COST_HALLUCINATIONS = [
        re.compile(r"\bcogs\s+(?:is|was|=)\s*\$?0(?:\.00)?\b", re.IGNORECASE),
        re.compile(r"\bgross\s+margin\s+(?:is|was|=)\s*(?:100%|0%)\b", re.IGNORECASE),
        re.compile(r"\bzero\s+(?:cost|cogs)\s+assumed\b", re.IGNORECASE),
    ]

    @classmethod
    def validate_request(cls, request: LLMRequest, strict: bool = False) -> list[str]:
        """
        Validate that the incoming LLM request does not instruct the model to
        perform raw mathematical calculation in place of deterministic analytics.
        """
        warnings: list[str] = []
        prompt_text = f"{request.prompt} {request.system_prompt or ''}"

        for pat in cls.PROHIBITED_ARITHMETIC_PROMPTS:
            if pat.search(prompt_text):
                msg = (
                    "Deterministic Invariant Warning: Prompt appears to request direct mathematical calculation. "
                    "All numerical metrics, aggregations, and statistics must be computed by deterministic tools/SQL."
                )
                warnings.append(msg)
                logger.warning(f"[Guard] {msg}")
                if strict and request.enforce_deterministic_invariants:
                    raise DeterministicInvariantViolationError(msg)

        return warnings

    @classmethod
    def validate_response(
        cls,
        response: LLMResponse,
        context: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> list[str]:
        """
        Validate that the model response did not fabricate financial truth or violate missing-cost invariants.
        """
        warnings: list[str] = []
        ctx = context or {}
        tool_results = ctx.get("tool_results", [])
        content = response.content

        # Check for missing-cost invariant violations
        has_missing_costs = False
        for tr in tool_results:
            if isinstance(tr, dict):
                res = tr.get("result", {})
                if isinstance(res, dict):
                    if res.get("cost_status") == "incomplete" or res.get("missing_unit_costs"):
                        has_missing_costs = True
                        break

        if has_missing_costs:
            for pat in cls.ZERO_COST_HALLUCINATIONS:
                if pat.search(content):
                    msg = (
                        "Data Integrity Invariant Violation: Response asserted zero cost ($0.00) or zero margin "
                        "when product catalog costs are missing. Missing cost metrics must be explicitly stated as incomplete."
                    )
                    warnings.append(msg)
                    logger.warning(f"[Guard] {msg}")
                    if strict:
                        raise DeterministicInvariantViolationError(msg)

        # Check for self-claimed arithmetic execution
        if re.search(r"\bi\s+(?:calculated|computed|multiplied|divided|added|subtracted)\s+the\s+(?:numbers|totals|revenue|profit)\s+(?:myself|manually)\b", content, re.IGNORECASE):
            msg = "Invariant Warning: LLM claimed to perform manual arithmetic calculations."
            warnings.append(msg)
            if strict:
                raise DeterministicInvariantViolationError(msg)

        return warnings

    @classmethod
    def is_pure_numerical_request(cls, request: LLMRequest) -> bool:
        """
        Check if the request is a deterministic numerical calculation that must bypass
        the LLM entirely and be handled strictly by SQL, Python analytics, or statistics engines.
        """
        if request.is_deterministic_numerical_request:
            return True
        prompt_text = f"{request.prompt}".strip().lower()
        if re.match(r"^[\d\.,\s\+\-\*\/\^\(\)]+=?$", prompt_text):
            return True
        if re.search(r"^(?:calculate|compute|solve)\s+[\d\.,\s\+\-\*\/\^\(\)]+(?:\s*=)?$", prompt_text):
            return True
        return False

    @classmethod
    def bypass_llm_for_deterministic(cls, request: LLMRequest) -> LLMResponse:
        """
        Produce a deterministic non-LLM response routing execution directly to
        the SQL/analytics engine, ensuring zero tokens and zero model inference are expended.
        """
        from app.agents.providers.models import LLMTaskCategory, ModelTier, TokenUsage
        cat = request.task_category if isinstance(request.task_category, LLMTaskCategory) else LLMTaskCategory.INTENT_UNDERSTANDING
        return LLMResponse(
            content="Deterministic numerical calculation bypassed LLM. Delegating strictly to SQL/analytics engine.",
            parsed_data={"bypassed_llm": True, "engine": "deterministic_sql_analytics"},
            task_category=cat,
            model_name="none-deterministic-engine",
            provider_name="sql_analytics_engine",
            tier=ModelTier.LOCAL_FALLBACK,
            bypassed_llm_for_deterministic=True,
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            estimated_cost_usd=0.0,
        )
