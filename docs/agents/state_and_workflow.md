# Agent State & LangGraph Workflow

## State Model (`AgentState`)

The NEXUS agent maintains a strongly-typed graph state dictionary defined in `app.agents.state.models.AgentState`.

```python
class AgentState(TypedDict, total=False):
    request_id: str
    user_query: str
    explanation_level: str
    reference_date: Optional[str]
    intent: Optional[Dict[str, Any]]
    resolved_dates: Dict[str, Any]
    analysis_plan: Optional[Dict[str, Any]]
    current_step_index: int
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    evidence: List[Dict[str, Any]]
    assumptions: List[str]
    limitations: List[str]
    evidence_status: str
    needs_clarification: bool
    clarification_question: Optional[str]
    is_unsupported: bool
    unsupported_reason: Optional[str]
    final_answer: Optional[str]
    calculations: List[Dict[str, Any]]
    tools_used: List[str]
    follow_up_questions: List[str]
    errors: List[str]
    iteration_count: int
    max_iterations: int
```

---

## State Transitions & Node Execution

### 1. `understand_request`
- Resolves natural language date references via `DateInterpreter.interpret()`.
- Identifies the business intent using `provider.classify_intent()`.
- Detects whether the query is outside supported business intelligence domains (`is_unsupported = True`).
- Detects missing parameters or extreme ambiguity (`needs_clarification = True`).

### 2. `create_plan`
- Consults available deterministic tools from `tool_registry.list_tools()`.
- Generates an `AnalysisPlan` containing an ordered list of `PlanStep` items.
- Example diagnostic plan:
  - Step 0: `get_financial_summary` (establishes overall period variance)
  - Step 1: `run_variance_analysis` (dissects change across products/categories)

### 3. `validate_plan`
- Validates that every proposed step references a registered tool in `ToolRegistry`.
- Validates that tool arguments satisfy the tool's Pydantic schema.
- Rejects invalid plans immediately, routing to error handling.

### 4. `execute_tool`
- Increments `iteration_count`.
- Enforces `iteration_count <= max_iterations` (default: 5).
- Invokes `tool_registry.execute(tool_name, session, arguments)`.
- Appends execution output to `tool_results` and attaches `EvidenceRecord` to `evidence`.

### 5. `inspect_result`
- Inspects whether the tool returned a success status or execution error.
- Appends error details to `errors` if execution failed.

### 6. `check_evidence`
- Assesses evidence sufficiency:
  - `PARTIAL`: Additional planned steps exist and iteration limit is not exceeded. Graphs loops back to `execute_tool`.
  - `SUFFICIENT`: All planned steps completed and valid analytical results exist. Graph transitions to `generate_explanation`.
  - `ERROR`: A critical tool or database failure occurred. Transitions to `generate_explanation` for graceful degradation.

### 7. `generate_explanation`
- Synthesizes grounded natural language tailored to `explanation_level`:
  - `simple`: Brief, plain business language summary with direct figures.
  - `manager`: Executive summary with key drivers, comparison percentages, and strategic caveats.
  - `analyst`: Full numerical breakdown, source tables, exact formulas, and top contributors.
  - `technical`: Full audit trail including analysis IDs, underlying database tables/columns, and statistical constraints.
- Suggests 2–3 context-aware follow-up questions.

---

## Controlled Iteration & Safeguards

To prevent non-terminating loops, the state machine implements hard limits:
- `max_iterations` defaults to `Settings.MAX_AGENT_ITERATIONS = 5`.
- `iteration_count` is checked prior to every tool execution.
- If the iteration ceiling is reached, execution gracefully halts, reporting partial findings and noting that the iteration limit was reached.
