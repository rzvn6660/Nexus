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
    LLMTaskCategory,
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

    # Prohibited mutating or destructive SQL operations
    DESTRUCTIVE_SQL_PATTERNS = [
        re.compile(r"\b(?:drop|truncate|delete|alter|insert|update|create|replace|upsert)\b", re.IGNORECASE),
        re.compile(r"\b(?:grant|revoke|attach|detach|reindex|vacuum)\b", re.IGNORECASE),
        re.compile(r"\b(?:exec|execute|call|pg_sleep|benchmark|sleep)\b", re.IGNORECASE),
        re.compile(r";\s*(?:drop|truncate|delete|alter|insert|update|create|exec)", re.IGNORECASE),
    ]

    # Whitelisted read-only analytical SQL statements (must start with SELECT, WITH, or EXPLAIN)
    READ_ONLY_SQL_START = re.compile(r"^\s*(?:explain\s+)?(?:select|with)\b", re.IGNORECASE)

    @classmethod
    def validate_sql(cls, sql_text: str, strict: bool = False) -> tuple[bool, str | None]:
        """
        Deterministically validate that an LLM-generated SQL query is strictly read-only and analytical.
        Blocks destructive DDL/DML, multi-statement injection, and administrative operations.

        Returns:
            (is_valid, rejection_reason)
        """
        if not sql_text or not sql_text.strip():
            return False, "SQL query is empty or missing."

        cleaned = sql_text.strip()
        # Remove SQL comments (-- comment and /* comment */) before validation
        cleaned_no_comments = re.sub(r"--[^\n]*", "", cleaned)
        cleaned_no_comments = re.sub(r"/\*.*?\*/", "", cleaned_no_comments, flags=re.DOTALL).strip()

        # Check for destructive SQL patterns
        for pat in cls.DESTRUCTIVE_SQL_PATTERNS:
            match = pat.search(cleaned_no_comments)
            if match:
                reason = f"Mutating SQL operations strictly prohibited in read-only analytical mode. Detected destructive keyword: '{match.group(0)}'"
                logger.warning(f"[Guard] {reason}")
                if strict:
                    raise DeterministicInvariantViolationError(reason)
                return False, reason

        # Must be a read-only statement: SELECT or WITH
        if not cls.READ_ONLY_SQL_START.match(cleaned_no_comments):
            reason = "SQL query must begin with read-only statement ('SELECT' or 'WITH')."
            logger.warning(f"[Guard] {reason}")
            if strict:
                raise DeterministicInvariantViolationError(reason)
            return False, reason

        # Check for multiple chained statements with semicolons
        statements = [s.strip() for s in cleaned_no_comments.split(";") if s.strip()]
        if len(statements) > 1:
            reason = "Multi-statement SQL queries are prohibited for analytical safety."
            logger.warning(f"[Guard] {reason}")
            if strict:
                raise DeterministicInvariantViolationError(reason)
            return False, reason

        return True, None

    @classmethod
    def validate_sql_plan(cls, plan: dict[str, Any], strict: bool = False) -> tuple[bool, str | None]:
        """
        Deterministically validate an LLM-generated SQL data plan.
        If any destructive queries or mutating statements are found, the plan is marked rejected.
        """
        if not isinstance(plan, dict):
            return True, None

        # Check if plan has explicit rejection already
        if plan.get("plan_type") == "rejected":
            return False, plan.get("rejection_reason", "Plan rejected")

        # Extract possible SQL query fields
        sql_query = plan.get("sql") or plan.get("query") or plan.get("sql_query") or plan.get("raw_sql")
        if sql_query and isinstance(sql_query, str):
            is_valid, reason = cls.validate_sql(sql_query, strict=strict)
            if not is_valid:
                plan["plan_type"] = "rejected"
                plan["rejection_reason"] = reason
                return False, reason

        # Also inspect steps in plan if steps exist
        steps = plan.get("steps") or []
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict):
                    step_sql = step.get("sql") or step.get("query")
                    if step_sql and isinstance(step_sql, str):
                        is_valid, reason = cls.validate_sql(step_sql, strict=strict)
                        if not is_valid:
                            plan["plan_type"] = "rejected"
                            plan["rejection_reason"] = reason
                            return False, reason

        return True, None

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
        Validate that the model response did not fabricate financial truth, violate missing-cost invariants,
        or attempt to generate destructive SQL operations.
        """
        warnings: list[str] = []
        ctx = context or {}
        tool_results = ctx.get("tool_results", [])
        content = response.content

        # Deterministic SQL validation for SQL planning tasks
        if response.task_category in (LLMTaskCategory.SQL_DATA_PLANNING, "sql_data_planning", "sql_planning"):
            if isinstance(response.parsed_data, dict):
                is_valid, reason = cls.validate_sql_plan(response.parsed_data, strict=strict)
                if not is_valid:
                    msg = f"SQL Safety Invariant Violation: {reason}"
                    warnings.append(msg)
                    logger.warning(f"[Guard] {msg}")
                    if strict:
                        raise DeterministicInvariantViolationError(msg)
            elif isinstance(response.content, str):
                for pat in cls.DESTRUCTIVE_SQL_PATTERNS:
                    match = pat.search(response.content)
                    if match:
                        msg = f"SQL Safety Invariant Violation: LLM response contains destructive operation '{match.group(0)}'."
                        warnings.append(msg)
                        logger.warning(f"[Guard] {msg}")
                        if strict:
                            raise DeterministicInvariantViolationError(msg)

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
