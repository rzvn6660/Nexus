"""Reproducible evaluation suite for NEXUS Phase 25C.2: Hybrid Retrieval and Fusion.

Compares:
1. Dense-only retrieval
2. Lexical-only retrieval
3. Hybrid RRF retrieval

Measures Recall@K, MRR (Mean Reciprocal Rank), and Precision@K across:
- Exact alphanumeric SKU queries
- Acronym and term queries
- Paraphrased semantic queries
- Malayalam native script queries
- Manglish transliteration queries
- Irrelevant / out-of-domain queries
- Cross-tenant isolation queries
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.models.base import Base
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.ingestion.models import DocumentMetadata
from app.rag.ingestion.service import DocumentIngestionService
from app.rag.rerank.providers.cross_scorer import LocalCrossScorerRerankProvider
from app.rag.retrieval.retriever import HybridRetriever
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Evaluation Benchmark Dataset (Phase 25C.4 Expanded Retail & Distribution Corpus)
# ---------------------------------------------------------------------------

BENCHMARK_DOCUMENTS = [
    {
        "doc_id": "doc_sku_catalog",
        "title": "Industrial Catalog Spec Sheet",
        "domain": "inventory",
        "business_id": "eval_tenant_main",
        "content": (
            "## Precision Motor Assembly\n"
            "Component SKU-PROD-9021-A is calibrated for high torque industrial robotics. "
            "Minimum wholesale order quantity is strictly 500 units per invoice batch."
        ),
    },
    {
        "doc_id": "doc_sku_cold_chain",
        "title": "Cold Chain Meat & Seafood Catalog",
        "domain": "inventory",
        "business_id": "eval_tenant_main",
        "content": (
            "## Frozen Seafood Distribution Specs\n"
            "Product SKU-SEAFOOD-9920-F is processed Atlantic Salmon fillets. "
            "Storage temperature must remain continuously below -18°C throughout transport. "
            "Lot traceability barcode BARCODE-SEA-7712 is required for regulatory compliance."
        ),
    },
    {
        "doc_id": "doc_accounting_rules",
        "title": "Enterprise Accounting Manual",
        "domain": "finance",
        "business_id": "eval_tenant_main",
        "content": (
            "## Inventory Valuation and Retention\n"
            "Inventory must be accounted for using the FIFO (First-In, First-Out) method. "
            "Customer Lifetime Value (LTV) must be computed over a trailing 36-month horizon."
        ),
    },
    {
        "doc_id": "doc_wholesale_terms",
        "title": "Wholesale Volume Tiers & Credit Terms",
        "domain": "finance",
        "business_id": "eval_tenant_main",
        "content": (
            "## Minimum Order Quantities and EDI Requirements\n"
            "Minimum Order Quantity (MOQ) for Tier 1 wholesale pricing is 250 cases. "
            "Net 30 commercial payment terms require verified D&B credit rating above 75. "
            "Electronic Data Interchange (EDI 850) purchase orders are mandatory for orders exceeding $10,000."
        ),
    },
    {
        "doc_id": "doc_cancellation_policy",
        "title": "Subscription Commercial Terms",
        "domain": "sales",
        "business_id": "eval_tenant_main",
        "content": (
            "## Consumer Cancellation Privileges\n"
            "Subscribers are legally entitled to terminate recurring service agreements "
            "within thirty solar days without incurring early departure surcharges or fees."
        ),
    },
    {
        "doc_id": "doc_perishable_policy",
        "title": "Perishable Spoilage and Return Guidelines",
        "domain": "operations",
        "business_id": "eval_tenant_main",
        "content": (
            "## Spoilage and Temperature Discrepancy Reporting\n"
            "Spoilage claims on perishable dairy and fresh produce must be submitted within 24 hours of delivery. "
            "Cold chain monitoring logs must prove temperature exceeded 4°C during transit. "
            "Standard non-perishable merchandise returns window is 30 calendar days from invoice."
        ),
    },
    {
        "doc_id": "doc_damaged_policy_active_2024",
        "title": "Damaged Freight SOP (2024 Active Standard)",
        "domain": "operations",
        "business_id": "eval_tenant_main",
        "content": (
            "## Damaged Freight Protocol (2024 SOP)\n"
            "Active protocol CODE-RMA-2024 requires photographic proof within 48 hours of carrier delivery. "
            "Vendor credit memo will be issued upon photographic inspection without mandatory return freight."
        ),
    },
    {
        "doc_id": "doc_damaged_policy_legacy_2023",
        "title": "Damaged Freight SOP (2023 Superseded)",
        "domain": "operations",
        "business_id": "eval_tenant_main",
        "content": (
            "## Superseded Freight Protocol (2023 SOP)\n"
            "Obsolete procedure CODE-RMA-2023 required physical RMA return within 14 business days. "
            "Vendor paid return freight via freight bill of lading (BOL)."
        ),
    },
    {
        "doc_id": "doc_spanish_distribution",
        "title": "Manual de Distribución y Cadena de Frío (Español)",
        "domain": "operations",
        "business_id": "eval_tenant_main",
        "content": (
            "## Reclamaciones por Cadena de Frío\n"
            "La política de devolución de productos perecederos requiere notificación en menos de 24 horas. "
            "Los productos refrigerados deben mantener una temperatura de transporte inferior a 4 grados centígrados."
        ),
    },
    {
        "doc_id": "doc_malayalam_profit",
        "title": "Malayalam Business Operations Guide",
        "domain": "finance",
        "business_id": "eval_tenant_main",
        "content": (
            "## ലാഭം കണക്കാക്കുന്ന രീതി\n"
            "റീട്ടെയിൽ ബിസിനസ്സിൽ ലാഭം കണക്കാക്കുന്നത് മൊത്തം വില്പന വരുമാനത്തിൽ നിന്ന് "
            "പ്രവർത്തന ചെലവുകൾ കുറച്ചാണ്. അറ്റാദായം കൃത്യമായി രേഖപ്പെടുത്തണം."
        ),
    },
    {
        "doc_id": "doc_manglish_seasonal",
        "title": "Kerala Retail Seasonal Notes",
        "domain": "sales",
        "business_id": "eval_tenant_main",
        "content": (
            "## Vilpana Seasonal Guidance\n"
            "Vilpana kooduthal ulla festival season samayathu customer discount "
            "പരമാവധി 15 percent aayirikkum. Stock theernnu pokathirikkaan shradhikkuka."
        ),
    },
    {
        "doc_id": "doc_isolated_alpha",
        "title": "Confidential Alpha Document",
        "domain": "finance",
        "business_id": "eval_tenant_secret",
        "content": (
            "## Restricted Access\n"
            "Internal token SECRET-ALPHA-TOKEN-999 is private to tenant alpha only."
        ),
    },
]

BENCHMARK_CASES = [
    {
        "query_id": "q1_sku_motor",
        "query": "SKU-PROD-9021-A",
        "category": "exact_sku",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_sku_catalog",
        "notes": "Exact alphanumeric SKU query; dense models typically struggle without keyword support",
    },
    {
        "query_id": "q2_sku_seafood",
        "query": "SKU-SEAFOOD-9920-F",
        "category": "exact_sku",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_sku_cold_chain",
        "notes": "Exact frozen seafood SKU lookup",
    },
    {
        "query_id": "q3_acronym_fifo",
        "query": "FIFO inventory valuation and LTV calculation",
        "category": "acronym_term",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_accounting_rules",
        "notes": "Financial acronyms (FIFO, LTV)",
    },
    {
        "query_id": "q4_acronym_moq_edi",
        "query": "Wholesale MOQ and EDI 850 threshold requirements",
        "category": "acronym_term",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_wholesale_terms",
        "notes": "B2B distribution acronyms (MOQ, EDI)",
    },
    {
        "query_id": "q5_policy_credit_terms",
        "query": "Net 30 commercial payment terms and credit rating requirements",
        "category": "business_policy",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_wholesale_terms",
        "notes": "Commercial B2B credit and payment policy",
    },
    {
        "query_id": "q6_policy_cold_chain",
        "query": "Cold chain storage temperature requirement for frozen seafood",
        "category": "business_policy",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_sku_cold_chain",
        "notes": "Cold chain distribution policy",
    },
    {
        "query_id": "q7_semantic_cancellation",
        "query": "How much time do clients have to cancel their plans without penalty?",
        "category": "paraphrased_semantic",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_cancellation_policy",
        "notes": "Zero lexical overlap with 'thirty solar days' / 'early departure surcharges'",
    },
    {
        "query_id": "q8_semantic_spoilage",
        "query": "How fast do we have to file claims when milk or produce arrives spoiled?",
        "category": "paraphrased_semantic",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_perishable_policy",
        "notes": "Paraphrased query matching 'within 24 hours of delivery'",
    },
    {
        "query_id": "q9_ambiguous_returns",
        "query": "What is the return window for products?",
        "category": "ambiguous_query",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_perishable_policy",
        "notes": "Ambiguous query matching both 30-day non-perishable and 24-hour perishable windows",
    },
    {
        "query_id": "q10_conflicting_rma",
        "query": "What is the current damaged freight RMA protocol and deadline?",
        "category": "conflicting_documents",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_damaged_policy_active_2024",
        "notes": "Tests active 2024 protocol CODE-RMA-2024 preference over superseded 2023 legacy",
    },
    {
        "query_id": "q11_malayalam_profit",
        "query": "റീട്ടെയിൽ ബിസിനസ്സിൽ ലാഭം കണക്കാക്കുന്നത്",
        "category": "malayalam_native",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_malayalam_profit",
        "notes": "Native Malayalam script query for profit calculation",
    },
    {
        "query_id": "q12_manglish_seasonal",
        "query": "vilpana kooduthal season discount",
        "category": "manglish_transliteration",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_manglish_seasonal",
        "notes": "Latin transliterated Malayalam terms (Manglish)",
    },
    {
        "query_id": "q13_spanish_distribution",
        "query": "devolución de productos perecederos y cadena de frío",
        "category": "multilingual_spanish",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": "doc_spanish_distribution",
        "notes": "Spanish query for perishable return and cold chain policy",
    },
    {
        "query_id": "q14_irrelevant_physics",
        "query": "Quantum gravity string theory holographic principle cosmology",
        "category": "irrelevant_out_of_domain",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": None,
        "notes": "Completely unrelated query, expects 0 relevant matches (no-result behavior)",
    },
    {
        "query_id": "q15_irrelevant_recipe",
        "query": "Authentic Italian wood-fired pizza dough recipe with yeast",
        "category": "irrelevant_out_of_domain",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": None,
        "notes": "Completely out-of-domain recipe query, expects 0 relevant matches",
    },
    {
        "query_id": "q16_tenant_isolation",
        "query": "SECRET-ALPHA-TOKEN-999",
        "category": "tenant_isolation_adversarial",
        "tenant_id": "eval_tenant_main",
        "expected_doc_id": None,
        "notes": "Querying another tenant's secret code must return 0 results",
    },
]


def setup_benchmark_environment(
    provider: BaseEmbeddingProvider | None = None,
) -> tuple[Session, HybridRetriever]:
    """Initialize an isolated in-memory SQLite database populated with benchmark docs."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_maker = sessionmaker(bind=engine)
    session = session_maker()

    emb_provider = provider or get_embedding_provider()
    ingestion_service = DocumentIngestionService(session, embedding_provider=emb_provider)

    for item in BENCHMARK_DOCUMENTS:
        meta = DocumentMetadata(
            title=item["title"],
            business_domain=item["domain"],
            source=f"{item['doc_id']}.md",
        )
        ingestion_service.ingest_text(
            text=item["content"],
            doc_type="markdown",
            metadata=meta,
            business_id=item["business_id"],
        )

    retriever = HybridRetriever(session, embedding_provider=emb_provider)
    return session, retriever


def evaluate_retrieval_mode(
    retriever: HybridRetriever,
    mode: str,  # "dense_only", "lexical_only", "hybrid_rrf"
    k: int = 3,
) -> dict[str, Any]:
    """Execute all benchmark queries under a specific retrieval mode and compute metrics."""
    hits: list[bool] = []
    reciprocal_ranks: list[float] = []
    precisions: list[float] = []
    latencies: list[float] = []
    query_results: list[dict[str, Any]] = []

    for case in BENCHMARK_CASES:
        query = case["query"]
        expected_doc = case["expected_doc_id"]
        tenant = case["tenant_id"]

        # Configure retrieval based on mode
        clean_q = query.strip()
        t_start = time.perf_counter()

        if mode == "dense_only":
            cands, _, _ = retriever._generate_dense_candidates(
                query=clean_q,
                domain=None,
                candidate_k=k,
                threshold=0.01,
                business_id=tenant,
            )
            retrieved_sources = [doc.source for _, doc, _ in cands[:k]]
        elif mode == "lexical_only":
            cands, _, _, _, _ = retriever._generate_lexical_candidates(
                query=clean_q,
                domain=None,
                candidate_k=k,
                business_id=tenant,
            )
            retrieved_sources = [doc.source for _, doc, _ in cands[:k]]
        elif mode == "hybrid_rrf_reranked":
            old_provider = retriever.rerank_provider
            retriever.rerank_provider = LocalCrossScorerRerankProvider()
            try:
                res = retriever.retrieve(clean_q, business_id=tenant, top_k=k)
                retrieved_sources = [c.source for c in res.chunks]
            finally:
                retriever.rerank_provider = old_provider
        else:  # hybrid_rrf baseline
            res = retriever.retrieve(clean_q, business_id=tenant, top_k=k)
            retrieved_sources = [c.source for c in res.chunks]

        q_lat_ms = (time.perf_counter() - t_start) * 1000
        latencies.append(q_lat_ms)

        # Calculate metrics for this query
        expected_source = f"{expected_doc}.md" if expected_doc else None
        if expected_source is None:
            # Irrelevant or cross-tenant query: true negative expected
            hit = len(retrieved_sources) == 0
            rr = 1.0 if hit else 0.0
            prec = 1.0 if hit else 0.0
        else:
            hit = expected_source in retrieved_sources
            if hit:
                rank = retrieved_sources.index(expected_source) + 1
                rr = 1.0 / rank
                prec = 1.0 / k  # Target doc retrieved
            else:
                rr = 0.0
                prec = 0.0

        hits.append(hit)
        reciprocal_ranks.append(rr)
        precisions.append(prec)

        query_results.append(
            {
                "query_id": case["query_id"],
                "category": case["category"],
                "expected": expected_doc,
                "retrieved": retrieved_sources,
                "hit": hit,
                "reciprocal_rank": round(rr, 4),
                "latency_ms": round(q_lat_ms, 2),
            }
        )

    n = len(BENCHMARK_CASES)
    recall_at_k = sum(hits) / max(n, 1)
    mrr = sum(reciprocal_ranks) / max(n, 1)
    precision_at_k = sum(precisions) / max(n, 1)
    avg_latency = sum(latencies) / max(n, 1)

    return {
        "mode": mode,
        "k": k,
        "recall_at_k": round(recall_at_k, 4),
        "mrr": round(mrr, 4),
        "precision_at_k": round(precision_at_k, 4),
        "avg_latency_ms": round(avg_latency, 2),
        "details": query_results,
    }


def run_full_benchmark() -> dict[str, Any]:
    """Run full comparative benchmark across Dense, Lexical, Hybrid RRF, and Reranked modes."""
    provider = get_embedding_provider()
    session, retriever = setup_benchmark_environment(provider)

    provider_info = {
        "provider_name": provider.provider_name,
        "model_name": provider.model_name,
        "dimension": provider.dimension,
        "is_mock": provider.provider_name == "mock",
    }

    results = {
        "provider": provider_info,
        "modes": {
            "dense_only": evaluate_retrieval_mode(retriever, "dense_only", k=3),
            "lexical_only": evaluate_retrieval_mode(retriever, "lexical_only", k=3),
            "hybrid_rrf": evaluate_retrieval_mode(retriever, "hybrid_rrf", k=3),
            "hybrid_rrf_reranked": evaluate_retrieval_mode(retriever, "hybrid_rrf_reranked", k=3),
        },
    }
    session.close()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RAG Hybrid Retrieval Benchmark")
    parser.add_argument("--json", action="store_true", help="Output raw JSON results")
    args = parser.parse_args()

    bench = run_full_benchmark()

    if args.json:
        print(json.dumps(bench, indent=2))
    else:
        prov = bench["provider"]
        print("=" * 80)
        print(" NEXUS RAG RETRIEVAL COMPARATIVE BENCHMARK (PHASE 25C.4)")
        print("=" * 80)
        print(
            f"Provider: {prov['provider_name']} | Model: {prov['model_name']} | "
            f"Dim: {prov['dimension']} | Mock: {prov['is_mock']}"
        )
        print("-" * 80)
        print(
            f"{'Mode':<22} | {'Recall@3':<10} | {'MRR':<10} | {'Precision@3':<12} | {'Avg Latency':<12}"
        )
        print("-" * 80)
        for mode, data in bench["modes"].items():
            print(
                f"{mode:<22} | {data['recall_at_k']:<10.4f} | {data['mrr']:<10.4f} | {data['precision_at_k']:<12.4f} | {data['avg_latency_ms']:<7.2f} ms"
            )
        print("=" * 80)
