# NEXUS Hybrid Retrieval Engine

## 1. Multi-Tier Retrieval Strategy

To avoid hallucination and ensure context relevance, NEXUS implements a multi-tier hybrid retrieval architecture:

```
User Query
    ↓
[Tier 1] Deterministic Semantic Resolution
    • Check KPI Ontology & canonical terms
    • Check exact synonyms
    • Detect ambiguities & out-of-scope requests
    ↓
[Tier 2] Vector Search over Knowledge Chunks
    • Generate query embedding
    • Apply metadata domain filter (if resolved)
    • Order by cosine similarity
    • Filter by similarity threshold
    ↓
[Tier 3] Verified Ontology Fallback
    • If no document chunks exceed threshold, synthesize verified context
      directly from registered KPI definition
    ↓
[Tier 4] Conflict Detection
    • Identify contradictory policies or thresholds across active documents
    ↓
Construct RetrievedContext & RAGEvidence Provenance
```

## 2. Provenance Evidence Structure

Every retrieved chunk is translated into a `RAGEvidence` record containing:
- `document_id`: Unique identifier of parent document
- `document_name`: Human-readable document title
- `chunk_id`: Unique chunk identifier
- `source`: Source file path or originating system
- `title`: Section or header title
- `similarity_score`: Vector cosine similarity score
- `retrieval_method`: Retrieval approach used (`exact_kpi_match`, `vector_search`, `metadata_filtered_vector`)
- `excerpt`: Context preview excerpt

## 3. Conflict Detection

When business documents from different departments or versions define thresholds differently (e.g. one document states a repeat customer has 2 orders, while another states 3 orders), the retriever flags `has_conflict=True` and populates `conflict_description`, alerting the user and agent rather than silently making an assumption.
