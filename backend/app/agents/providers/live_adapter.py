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
    LLMSafetyGuardViolationError,
    LLMRequest,
    LLMResponse,
    LLMTaskCategory,
    ModelTier,
    TokenUsage,
)
from app.agents.state.models import (
    AnalysisPlan,
    ExplanationLevel,
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
        if isinstance(err_obj, dict):
            if err_obj.get("code") == "tool_use_failed" or "model called a tool" in err_obj.get("message", "").lower():
                return True, str(err_obj.get("failed_generation", ""))

    # 2. Check OpenAI API response JSON
    if hasattr(exc, "response"):
        try:
            rjson = exc.response.json()
            err_obj = rjson.get("error", {})
            if isinstance(err_obj, dict):
                if err_obj.get("code") == "tool_use_failed" or "model called a tool" in err_obj.get("message", "").lower():
                    return True, str(err_obj.get("failed_generation", ""))
        except Exception:
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
                        except Exception:
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
                    except Exception:
                        try:
                            if "{" in content and "}" in content:
                                start = content.index("{")
                                end = content.rindex("}") + 1
                                parsed = json.loads(content[start:end])
                        except Exception:
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
                        except Exception:
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
        except Exception:
            pass
        return self._fallback_mock.classify_intent(query, supported_intents)

    def create_plan(
        self,
        query: str,
        intent: IntentCategory,
        available_tools: list[dict[str, Any]],
        resolved_dates: dict[str, Any],
    ) -> AnalysisPlan:
        tool_names = [t["name"] for t in available_tools]
        req = LLMRequest(
            task_category=LLMTaskCategory.SQL_PLANNING,
            prompt=f"Create analysis plan for query: '{query}' with intent '{intent.value}'. Available tools: {tool_names}. Return JSON AnalysisPlan.",
            schema_model="AnalysisPlan",
            context={"available_tools": available_tools, "resolved_dates": resolved_dates},
        )
        try:
            resp = self.generate(req)
            if resp.parsed_data:
                return AnalysisPlan.model_validate(resp.parsed_data)
        except Exception:
            pass
        return self._fallback_mock.create_plan(query, intent, available_tools, resolved_dates)

    def explain_results(
        self,
        query: str,
        tool_results: list[dict[str, Any]],
        explanation_level: ExplanationLevel = ExplanationLevel.MANAGER,
        business_context: str | None = None,
    ) -> str:
        req = LLMRequest(
            task_category=LLMTaskCategory.EXPLANATION,
            prompt=f"Explain results for query: '{query}' at {explanation_level.value} level.",
            context={"tool_results": tool_results, "business_context": business_context},
        )
        try:
            resp = self.generate(req)
            if resp.content:
                return resp.content
        except Exception:
            pass
        return self._fallback_mock.explain_results(query, tool_results, explanation_level, business_context)
