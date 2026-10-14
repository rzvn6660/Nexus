"""OpenAI-compatible live LLM provider adapter for controlled benchmarking and evaluation."""

import json
import logging
import os
import time
from typing import Any

from app.agents.providers.base import BaseLLMProvider
from app.agents.providers.mock import MockLLMProvider
from app.agents.providers.models import (
    LLMProviderError,
    LLMProviderTimeoutError,
    LLMProviderUnavailableError,
    LLMRequest,
    LLMResponse,
    LLMSafetyGuardViolationError,
    LLMTaskCategory,
    ModelTier,
    TokenUsage,
)
from app.agents.state.models import (
    AnalysisPlan,
    ExplanationLevel,
    GroundedExplanation,
    IntentCategory,
    IntentResult,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


def _is_transient_error(exc: Exception) -> bool:
    """Check if error is transient (HTTP 503, 502, 504, 429, capacity spike, temporary unavailability)."""
    status_code = getattr(exc, "status_code", None)
    if status_code in (503, 502, 504, 429):
        return True

    code = getattr(exc, "code", None)
    if code in (503, 429):
        return True

    exc_str = str(exc).lower()
    transient_indicators = [
        "503",
        "unavailable",
        "high demand",
        "rate limit",
        "resource_exhausted",
        "temporarily unavailable",
        "capacity",
        "try again later",
    ]
    return any(ind in exc_str for ind in transient_indicators)


def _extract_failed_tool_generation(exc: Exception) -> tuple[bool, str]:
    """Inspect exception to detect unexpected tool call emissions (e.g. Groq tool_use_failed)."""
    # 1. Check OpenAI API exception body dict
    if hasattr(exc, "body") and isinstance(exc.body, dict):
        err_obj = exc.body.get("error", {})
        if isinstance(err_obj, dict) and (
            err_obj.get("code") == "tool_use_failed"
            or "model called a tool" in err_obj.get("message", "").lower()
        ):
            return True, str(err_obj.get("failed_generation", ""))

    # 2. Check OpenAI API response JSON
    if hasattr(exc, "response"):
        try:
            rjson = exc.response.json()
            err_obj = rjson.get("error", {})
            if isinstance(err_obj, dict) and (
                err_obj.get("code") == "tool_use_failed"
                or "model called a tool" in err_obj.get("message", "").lower()
            ):
                return True, str(err_obj.get("failed_generation", ""))
        except Exception:  # noqa: BLE001, S110
            pass

    # 3. Check raw string
    exc_str = str(exc).lower()
    if "tool choice is none, but model called a tool" in exc_str:
        return True, ""

    return False, ""


class OpenAICompatibleLiveProvider(BaseLLMProvider):
    """
    Standardized provider communicating with any OpenAI-compatible API:
    - Ollama (local)
    - Groq
    - Google Gemini (via OpenAI-compatible endpoint)
    - DeepSeek
    - Qwen (Alibaba DashScope / OpenRouter)
    - Kimi (Moonshot AI K2 / K2.6)
    - xAI Grok
    - OpenRouter
    - OpenAI
    
    Guarantees:
    - Never makes external network calls without explicit configuration and permission.
    - Captures latency, prompt/completion tokens, and returns unified LLMResponse.
    - Handles timeouts and schema validation cleanly.
    - Bounded retry/backoff for transient HTTP 503/UNAVAILABLE or rate-limit responses.
    - Handles unexpected tool calls in completion-only and tool-enabled scenarios.
    """

    def __init__(
        self,
        provider_name: str,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_env_var: str | None = None,
        is_local: bool = False,
        timeout_seconds: float = 20.0,
        allow_external: bool = False,
        max_retries: int = 3,
        retry_delay_seconds: float = 1.5,
    ) -> None:
        self._provider_name = provider_name
        self.model_name = model_name
        self.base_url = base_url
        self.is_local = is_local
        self.timeout_seconds = timeout_seconds
        self.api_key_env_var = api_key_env_var
        self.allow_external = allow_external
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

        # Resolve API key
        resolved_key = api_key
        if not resolved_key and api_key_env_var:
            resolved_key = getattr(settings, api_key_env_var, None) or os.getenv(api_key_env_var)
            if not resolved_key and api_key_env_var == "KIMI_API_KEY":
                resolved_key = getattr(settings, "MOONSHOT_API_KEY", None) or os.getenv("MOONSHOT_API_KEY")
        self.api_key = resolved_key or ("ollama" if is_local else None)
        self._fallback_mock = MockLLMProvider()

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def is_configured(self, allow_external: bool = False) -> tuple[bool, str]:
        """Check if provider has credentials and permissions to execute."""
        if self.is_local:
            return True, "LOCAL_PROVIDER_AVAILABLE"
        effective_allow = allow_external or self.allow_external or getattr(settings, "LLM_ALLOW_EXTERNAL_CALLS", False)
        if not effective_allow:
            return False, "EXTERNAL_CALLS_DISABLED"
        if not self.api_key:
            return False, f"MISSING_API_KEY_{self.api_key_env_var or 'NOT_SET'}"
        return True, "CONFIGURED"

    def _get_client(self, allow_external: bool = False):
        configured, reason = self.is_configured(allow_external=allow_external)
        if not configured:
            if "EXTERNAL_CALLS_DISABLED" in reason:
                raise LLMSafetyGuardViolationError(
                    f"External call to '{self._provider_name}' blocked: LLM_ALLOW_EXTERNAL_CALLS is disabled."
                )
            raise LLMProviderUnavailableError(
                f"Provider '{self._provider_name}' unavailable: {reason}."
            )

        from openai import OpenAI
        client_kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "api_key": self.api_key or "local",
            "timeout": self.timeout_seconds,
        }
        if self.base_url and "openrouter" in self.base_url.lower():
            client_kwargs["default_headers"] = {
                "HTTP-Referer": "https://nexus.local",
                "X-Title": "NEXUS Benchmark",
            }
        return OpenAI(**client_kwargs)

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Execute request using live provider or report error."""
        effective_allow = self.allow_external or getattr(settings, "LLM_ALLOW_EXTERNAL_CALLS", False)
        client = self._get_client(allow_external=effective_allow)

        system_prompt = request.system_prompt or "You are NEXUS, an enterprise business intelligence AI."
        user_prompt = request.prompt
        if request.context:
            user_prompt += f"\n\nContext:\n{json.dumps(request.context, default=str)}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        t0 = time.perf_counter()

        # Build request parameters
        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 1000,
        }

        # Check for tool definitions
        raw_tools = request.context.get("available_tools") or request.metadata.get("available_tools") or []
        tools_def = []
        if isinstance(raw_tools, list) and raw_tools:
            for t in raw_tools:
                if isinstance(t, dict):
                    tools_def.append({
                        "type": "function",
                        "function": {
                            "name": t.get("name", "tool"),
                            "description": t.get("description", f"Tool {t.get('name')}"),
                            "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                        }
                    })
                elif isinstance(t, str):
                    tools_def.append({
                        "type": "function",
                        "function": {
                            "name": t,
                            "description": f"Tool {t}",
                            "parameters": {"type": "object", "properties": {}},
                        }
                    })

        # Register tools or structured response format
        # Hard Safety Guard: Candidates lacking tool capability (specifically Qwen) must NOT receive unrestricted autonomous tool execution
        allow_autonomous_tools = self.provider_name.lower() not in ("openrouter-qwen", "qwen")
        is_tool_scenario = (
            allow_autonomous_tools
            and (
                request.task_category in (LLMTaskCategory.TOOL_SELECTION, "tool_selection")
                or bool(tools_def and not request.schema_model)
            )
        )
        if is_tool_scenario and tools_def:
            kwargs["tools"] = tools_def
            kwargs["tool_choice"] = "auto"
        elif request.schema_model:
            kwargs["response_format"] = {"type": "json_object"}

        # Bounded retry loop for transient capacity/rate-limit errors
        attempt = 0
        while True:
            try:
                completion = client.chat.completions.create(**kwargs)
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)

                msg = completion.choices[0].message
                content = msg.content or getattr(msg, "reasoning", "") or ""
                usage = TokenUsage(
                    prompt_tokens=getattr(completion.usage, "prompt_tokens", 0) if completion.usage else 0,
                    completion_tokens=getattr(completion.usage, "completion_tokens", 0) if completion.usage else 0,
                    total_tokens=getattr(completion.usage, "total_tokens", 0) if completion.usage else 0,
                )

                parsed = None

                # Handle native tool calls if emitted
                if getattr(msg, "tool_calls", None):
                    tool_calls_list = []
                    selected_tools = []
                    for tc in msg.tool_calls:
                        func = getattr(tc, "function", None)
                        fname = getattr(func, "name", "unknown") if func else "unknown"
                        fargs = getattr(func, "arguments", "{}") if func else "{}"
                        try:
                            parsed_args = json.loads(fargs) if isinstance(fargs, str) else fargs
                        except Exception:  # noqa: BLE001
                            parsed_args = {"raw": fargs}
                        tool_calls_list.append({"name": fname, "arguments": parsed_args})
                        selected_tools.append(fname)

                    parsed = {
                        "tool_calls": tool_calls_list,
                        "selected_tools": selected_tools,
                        "steps": [
                            {
                                "step_index": i,
                                "tool_name": tc["name"],
                                "purpose": f"Execute {tc['name']}",
                                "arguments": tc["arguments"] if isinstance(tc["arguments"], dict) else {},
                            }
                            for i, tc in enumerate(tool_calls_list)
                        ],
                        "goal": f"Execute {', '.join(selected_tools)}",
                    }
                    if not content:
                        content = json.dumps(parsed)

                # Parse JSON content if not already parsed
                if parsed is None and content:
                    try:
                        parsed = json.loads(content)
                    except Exception:  # noqa: BLE001
                        try:
                            if "{" in content and "}" in content:
                                start = content.index("{")
                                end = content.rindex("}") + 1
                                parsed = json.loads(content[start:end])
                        except Exception:  # noqa: BLE001
                            parsed = None

                # Normalize steps into valid PlanStep structure if emitted as strings or dicts with field aliases
                if parsed and isinstance(parsed.get("steps"), list):
                    normalized_steps = []
                    for i, s in enumerate(parsed["steps"]):
                        if isinstance(s, dict):
                            t_name = s.get("tool_name") or s.get("tool") or s.get("name") or "analytical_tool"
                            purp = s.get("purpose") or s.get("description") or s.get("goal") or f"Step {i + 1}"
                            args = s.get("arguments") or s.get("parameters") or s.get("args") or {}
                            normalized_steps.append({
                                "step_index": s.get("step_index", s.get("step", i)),
                                "tool_name": str(t_name),
                                "purpose": str(purp),
                                "arguments": args if isinstance(args, dict) else {},
                            })
                        elif isinstance(s, str):
                            tool_name = "analytical_step"
                            for candidate_tool in (raw_tools or []):
                                t_name = candidate_tool.get("name") if isinstance(candidate_tool, dict) else candidate_tool
                                if t_name and t_name in s:
                                    tool_name = t_name
                                    break
                            normalized_steps.append({
                                "step_index": i,
                                "tool_name": tool_name,
                                "purpose": s,
                                "arguments": {},
                            })
                    parsed["steps"] = normalized_steps

                return LLMResponse(
                    content=content,
                    parsed_data=parsed,
                    task_category=request.task_category,
                    model_name=self.model_name,
                    provider_name=self._provider_name,
                    tier=request.preferred_tier or ModelTier.LOW_COST,
                    latency_ms=latency_ms,
                    usage=usage,
                )

            except Exception as exc:
                # 0. Check if model does not support tools (e.g. Ollama phi3:latest)
                if "does not support tools" in str(exc).lower() and "tools" in kwargs:
                    logger.info(f"Model '{self.model_name}' does not support tools; retrying without tool parameters.")
                    kwargs.pop("tools", None)
                    kwargs.pop("tool_choice", None)
                    continue

                # 1. Check for unexpected tool call failure in completion-only scenario
                is_unexpected_tool, failed_gen = _extract_failed_tool_generation(exc)
                if is_unexpected_tool:
                    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                    parsed = None
                    if failed_gen:
                        try:
                            parsed = json.loads(failed_gen)
                            if isinstance(parsed, dict) and "name" in parsed:
                                parsed["selected_tools"] = [parsed["name"]]
                                parsed["tool_calls"] = [{"name": parsed["name"], "arguments": parsed.get("arguments", {})}]
                                parsed["steps"] = [{
                                    "step_index": 0,
                                    "tool_name": parsed["name"],
                                    "purpose": f"Execute {parsed['name']}",
                                    "arguments": parsed.get("arguments", {}),
                                }]
                                parsed["goal"] = f"Execute {parsed['name']}"
                        except Exception:  # noqa: BLE001
                            parsed = {"raw_generation": failed_gen}

                    return LLMResponse(
                        content=failed_gen or "Unexpected tool call emitted without tool binding.",
                        parsed_data=parsed,
                        task_category=request.task_category,
                        model_name=self.model_name,
                        provider_name=self._provider_name,
                        tier=request.preferred_tier or ModelTier.LOW_COST,
                        latency_ms=latency_ms,
                        usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
                        warnings=["Model emitted unexpected tool call when tool choice was disabled."],
                    )

                # 2. Check transient capacity/rate-limit error for bounded retry
                if attempt < self.max_retries and _is_transient_error(exc):
                    attempt += 1
                    delay = min(self.retry_delay_seconds * (2 ** (attempt - 1)), 5.0)
                    logger.warning(
                        f"Transient error from '{self._provider_name}' (attempt {attempt}/{self.max_retries}): {exc}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    continue

                # 3. Retries exhausted or non-transient error: preserve original error classification
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                exc_str = str(exc).lower()
                if "timeout" in exc_str:
                    raise LLMProviderTimeoutError(f"Provider '{self._provider_name}' timed out after {latency_ms}ms") from exc
                if _is_transient_error(exc):
                    raise LLMProviderUnavailableError(f"Provider '{self._provider_name}' unavailable: {exc}") from exc
                raise LLMProviderError(f"Provider '{self._provider_name}' call failed: {exc}") from exc

    def classify_intent(self, query: str, supported_intents: list[str]) -> IntentResult:
        req = LLMRequest(
            task_category=LLMTaskCategory.INTENT_UNDERSTANDING,
            prompt=f"Classify query into one of {supported_intents}: '{query}'. Return JSON with keys: category, confidence, reasoning.",
            schema_model="IntentResult",
        )
        try:
            resp = self.generate(req)
            if resp.parsed_data:
                return IntentResult.model_validate(resp.parsed_data)
        except Exception:  # noqa: BLE001, S110
            pass
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
        sys_prompt, user_prompt = TaskPromptBuilder.build_planning_prompt(
            query=query,
            intent=intent,
            available_tools=available_tools,
            resolved_dates=resolved_dates,
            semantic_context=semantic_context,
            business_context=(semantic_context or {}).get("business_context"),
        )
        req = LLMRequest(
            task_category=LLMTaskCategory.STRUCTURED_OUTPUT,
            prompt=user_prompt,
            system_prompt=sys_prompt,
            schema_model="AnalysisPlan",
            context={"available_tools": available_tools, "resolved_dates": resolved_dates, "semantic_context": semantic_context},
        )
        try:
            resp = self.generate(req)
            if resp.parsed_data:
                plan = AnalysisPlan.model_validate(resp.parsed_data)
                plan.is_fallback = getattr(resp, "is_fallback", False)
                plan.fallback_reason = getattr(resp, "fallback_reason", None)
                plan.llm_provider = getattr(resp, "provider_name", self._provider_name)
                plan.llm_model = getattr(resp, "model_name", self.model_name)

                # Tool validation
                from app.agents.tools.registry import tool_registry
                is_valid = True
                invalid_reason = ""
                for step in plan.steps:
                    if not tool_registry.has_tool(step.tool_name):
                        is_valid = False
                        invalid_reason = f"Proposed tool '{step.tool_name}' is not in registered tool catalog"
                        break
                    t = tool_registry.get_tool(step.tool_name)
                    if t:
                        try:
                            t.input_schema.model_validate(step.arguments)
                        except Exception as ve:  # noqa: BLE001
                            is_valid = False
                            invalid_reason = f"Tool '{step.tool_name}' argument schema validation failed: {ve}"
                            break

                if is_valid:
                    return plan
                else:
                    fallback_plan = self._fallback_mock.create_plan(
                        query, intent, available_tools, resolved_dates, semantic_context=semantic_context
                    )
                    fallback_plan.is_fallback = True
                    fallback_plan.fallback_reason = sanitize_fallback_reason(f"Malformed structured output: {invalid_reason}")
                    fallback_plan.llm_provider = self._provider_name
                    fallback_plan.llm_model = self.model_name
                    return fallback_plan
        except Exception as exc:  # noqa: BLE001
            fallback_plan = self._fallback_mock.create_plan(
                query, intent, available_tools, resolved_dates, semantic_context=semantic_context
            )
            fallback_plan.is_fallback = True
            fallback_plan.fallback_reason = sanitize_fallback_reason(str(exc))
            fallback_plan.llm_provider = self._provider_name
            fallback_plan.llm_model = self.model_name
            return fallback_plan

        fallback_plan = self._fallback_mock.create_plan(
            query, intent, available_tools, resolved_dates, semantic_context=semantic_context
        )
        fallback_plan.is_fallback = True
        fallback_plan.fallback_reason = sanitize_fallback_reason("Live provider returned empty response")
        fallback_plan.llm_provider = self._provider_name
        fallback_plan.llm_model = self.model_name
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
        """Synthesize structured, schema-validated GroundedExplanation via live model."""
        from app.agents.providers.guard import DeterministicCalculationGuard
        from app.agents.providers.prompts import TaskPromptBuilder, sanitize_fallback_reason
        from app.agents.state.models import GroundedExplanation

        t_results = tool_results or []
        ev_records = evidence or []
        rag_records = rag_evidence or []
        is_plan_fallback = getattr(plan, "is_fallback", False) if plan else False
        plan_fallback_reason = getattr(plan, "fallback_reason", None) if plan else None

        if not self._allow_external and not self._is_local:
            fallback_exp = self._fallback_mock.explain_results_structured(
                query=query,
                plan=plan,
                tool_results=t_results,
                evidence=ev_records,
                explanation_level=explanation_level,
                business_context=business_context,
                semantic_context=semantic_context,
                warnings=warnings,
                rag_evidence=rag_records,
            )
            fallback_exp.is_fallback = True
            fallback_exp.fallback_reason = sanitize_fallback_reason("External calls disabled by configuration.")
            fallback_exp.llm_provider = self._provider_name
            fallback_exp.llm_model = self.model_name
            return fallback_exp

        sys_prompt, user_prompt = TaskPromptBuilder.build_explanation_prompt(
            query=query,
            plan=plan,
            tool_results=t_results,
            evidence=ev_records,
            explanation_level=explanation_level,
            business_context=business_context,
            is_fallback=is_plan_fallback,
            fallback_reason=plan_fallback_reason,
            semantic_context=semantic_context,
            warnings=warnings,
            rag_evidence=rag_records,
        )
        req = LLMRequest(
            task_category=LLMTaskCategory.STRUCTURED_OUTPUT,
            prompt=user_prompt,
            system_prompt=sys_prompt,
            schema_model="GroundedExplanation",
            context={
                "tool_results": t_results,
                "evidence": ev_records,
                "explanation_level": explanation_level.value if hasattr(explanation_level, "value") else str(explanation_level),
                "business_context": business_context,
                "semantic_context": semantic_context,
                "warnings": warnings,
                "rag_evidence": rag_records,
            },
        )
        try:
            exp_instance, resp = self.generate_structured(req, GroundedExplanation)
            if getattr(resp, "is_fallback", False):
                fallback_exp = self._fallback_mock.explain_results_structured(
                    query=query,
                    plan=plan,
                    tool_results=t_results,
                    evidence=ev_records,
                    explanation_level=explanation_level,
                    business_context=business_context,
                    semantic_context=semantic_context,
                    warnings=warnings,
                    rag_evidence=rag_records,
                )
                fallback_exp.is_fallback = True
                fallback_exp.fallback_reason = sanitize_fallback_reason(getattr(resp, "fallback_reason", None))
                fallback_exp.llm_provider = self._provider_name
                fallback_exp.llm_model = self.model_name
                return fallback_exp

            # Deterministic Grounding & Verification
            is_valid, validation_err = DeterministicCalculationGuard.validate_grounded_explanation(
                explanation=exp_instance,
                tool_results=t_results,
                evidence=ev_records,
                rag_evidence=rag_records,
                semantic_context=semantic_context,
            )
            if not is_valid:
                fallback_exp = self._fallback_mock.explain_results_structured(
                    query=query,
                    plan=plan,
                    tool_results=t_results,
                    evidence=ev_records,
                    explanation_level=explanation_level,
                    business_context=business_context,
                    semantic_context=semantic_context,
                    warnings=warnings,
                    rag_evidence=rag_records,
                )
                fallback_exp.is_fallback = True
                fallback_exp.fallback_reason = sanitize_fallback_reason(f"Ungrounded explanation: {validation_err}")
                fallback_exp.llm_provider = self._provider_name
                fallback_exp.llm_model = self.model_name
                return fallback_exp

            exp_instance.is_fallback = False
            exp_instance.fallback_reason = None
            exp_instance.llm_provider = self._provider_name
            exp_instance.llm_model = self.model_name
            return exp_instance

        except Exception as exc:  # noqa: BLE001
            fallback_exp = self._fallback_mock.explain_results_structured(
                query=query,
                plan=plan,
                tool_results=t_results,
                evidence=ev_records,
                explanation_level=explanation_level,
                business_context=business_context,
                semantic_context=semantic_context,
                warnings=warnings,
                rag_evidence=rag_records,
            )
            fallback_exp.is_fallback = True
            fallback_exp.fallback_reason = sanitize_fallback_reason(str(exc))
            fallback_exp.llm_provider = self._provider_name
            fallback_exp.llm_model = self.model_name
            return fallback_exp

    def explain_results(
        self,
        query: str,
        plan: AnalysisPlan | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        explanation_level: ExplanationLevel = ExplanationLevel.MANAGER,
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
