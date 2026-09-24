# NEXUS Phase 5 — Limitations & Phase Boundaries

## 1. Phase 5 Boundaries

Phase 5 strictly focuses on **Business Context RAG and Semantic Layer** capabilities. The following features are explicitly excluded from Phase 5 and locked for subsequent releases:

- **Predictive ML & Forecasting (Phase 7)**: No ARIMA, Prophet, or churn prediction models.
- **Autonomous Investigation & Root-Cause Scanning (Phase 6)**: The agent operates only upon explicit user invocation.
- **Background Cron Monitoring**: No background workers or daemon monitoring.
- **Voice Interface**: Purely REST and JSON API.
- **Personal Memory & Reminders**: No personal user preference storage or conversational memory across sessions.
- **Arbitrary SQL / Code Execution**: The agent cannot execute raw SQL or shell commands.

## 2. Technical Limitations

1. **Embedding Vocabulary in Mock Mode**: The `MockEmbeddingProvider` uses token and n-gram feature hashing with $L_2$ normalization. While deterministic and accurate for keyword-overlapping business concepts, production semantic subtlety requires configuring `EMBEDDING_PROVIDER=openai`.
2. **Encrypted PDFs**: Encrypted or password-protected PDF files cannot be indexed and are rejected during upload.
3. **Table Extraction in PDFs**: Complex multi-column tabular data inside PDFs is converted to linear text. For precise tabular data, structured CSV ingestion via the Phase 2 Data Layer should be used.
