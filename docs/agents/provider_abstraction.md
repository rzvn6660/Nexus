# LLM Provider Abstraction & Testing Strategy

## Overview

To avoid vendor lock-in and enable zero-cost, lightning-fast automated testing, NEXUS decouples its agentic orchestration engine from specific model APIs via an abstract interface: `BaseLLMProvider`.

```
                  BaseLLMProvider
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
MockLLMProvider                   OpenAIProvider
(Deterministic / Offline)         (Production Structured Output)
```

---

## Provider Interface (`BaseLLMProvider`)

```python
class BaseLLMProvider(ABC):
    @abstractmethod
    def classify_intent(self, query: str, supported_intents: List[str]) -> IntentResult:
        """Classify query into a supported analytical intent."""
        pass

    @abstractmethod
    def create_plan(
        self,
        query: str,
        intent: IntentCategory,
        available_tools: List[Dict[str, Any]],
        resolved_dates: Dict[str, Any],
    ) -> AnalysisPlan:
        """Formulate a structured, inspectable multi-step analysis plan."""
        pass

    @abstractmethod
    def explain_results(
        self,
        query: str,
        plan: Optional[AnalysisPlan],
        tool_results: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        explanation_level: ExplanationLevel,
    ) -> str:
        """Synthesize natural language narrative grounded in tool results."""
        pass
```

---

## Implementations

### 1. `MockLLMProvider`
- **Purpose**: Fast, reproducible, deterministic testing and offline local development.
- **Capabilities**:
  - Classifies intents across all 10 supported categories.
  - Builds structured single-step and multi-step plans (e.g. diagnostic variance decomposition).
  - Generates role-based explanations strictly using numbers present in `tool_results`.
  - Zero external API dependencies, zero costs, and sub-millisecond execution times.

### 2. `OpenAIProvider`
- **Purpose**: Production deployment using models such as `gpt-4o`.
- **Structured Outputs**: Uses OpenAI JSON schema formatting to enforce typed responses for intent and analysis planning.
- **Graceful Fallback**: If `OPENAI_API_KEY` is omitted in development or test runs, automatically falls back to `MockLLMProvider` without crashing.

---

## Provider Configuration

Configured via environment variables in `.env`:

```env
# AI / LLM Configuration
DEFAULT_LLM_PROVIDER="mock"      # mock | openai
DEFAULT_LLM_MODEL="gpt-4o"
OPENAI_API_KEY=""
MAX_AGENT_ITERATIONS=5
DEFAULT_EXPLANATION_LEVEL="manager" # simple | manager | analyst | technical
```

In automated test runs (`APP_ENV="test"`), `get_llm_provider()` automatically returns `MockLLMProvider`, guaranteeing 100% determinism in CI.
