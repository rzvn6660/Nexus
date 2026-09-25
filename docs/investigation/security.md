# Security & Guardrails

## Threat Model & Invariants

1. **Strict Tool Whitelisting**:
   - The Investigation Engine only executes tools registered in `ToolRegistry`.
   - Arbitrary SQL, Python scripting, and shell execution are strictly prohibited.

2. **Schema Validation**:
   - Every tool invocation validates arguments against strong Pydantic schemas before execution.
   - Malformed inputs fail fast with structured errors.

3. **Untrusted RAG Data**:
   - Documents retrieved from pgvector are labeled as `UNTRUSTED_RETRIEVED_BUSINESS_CONTEXT`.
   - LLMs and synthesis engines treat RAG text purely as passive data, never as system instructions.

4. **Resource Constraints**:
   - Maximum investigation steps: 8 (`MAX_INVESTIGATION_STEPS`).
   - Maximum execution timeouts per tool: 30 seconds.
   - Database connection pooling prevents connection starvation.
