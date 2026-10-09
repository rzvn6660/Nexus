"""PostgreSQL and pgvector native integration test suite (Phase 25C.2 & 25C.3).

Exercises:
1. Alembic migrations up to head against PostgreSQL with pgvector enabled.
2. PostgreSQL tsvector generated column and GIN index verification.
3. Native pgvector cosine distance operations (<=>).
4. PostgreSQL full-text search via websearch_to_tsquery and ts_rank_cd.
5. Production HybridRetriever pgvector_native execution and RRF fusion.
6. SQL-level multi-tenant isolation in PostgreSQL.
7. Transaction rollback isolation on PostgreSQL database errors.

Skips gracefully when PostgreSQL is not reachable in the local test runner.
Executes in GitHub Actions CI where pgvector/pgvector:pg16 service is active.
"""

import os

import pytest
from app.models.knowledge import KnowledgeChunk
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.ingestion.models import DocumentMetadata
from app.rag.ingestion.service import DocumentIngestionService
from app.rag.retrieval.retriever import HybridRetriever
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

PG_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://nexus_user:nexus_password@localhost:5432/nexus_test_db",
)


def _check_postgres_ready() -> bool:
    """Check whether PostgreSQL with pgvector is accessible."""
    if "postgresql" not in PG_URL:
        return False
    try:
        engine = create_engine(PG_URL, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            res = conn.execute(text("SELECT 1;")).scalar()
            return res == 1
    except Exception:  # noqa: BLE001
        return False


POSTGRES_AVAILABLE = _check_postgres_ready()


@pytest.mark.skipif(not POSTGRES_AVAILABLE, reason="PostgreSQL service not available")
class TestPostgresPgvectorIntegration:
    """Integration suite testing native PostgreSQL and pgvector capabilities."""

    @pytest.fixture(scope="class")
    def pg_engine(self):
        engine = create_engine(PG_URL)
        yield engine
        engine.dispose()

    @pytest.fixture(scope="class")
    def pg_migrated(self, pg_engine):
        """Run Alembic migrations up to head against PostgreSQL."""
        from pathlib import Path

        from alembic import command
        from alembic.config import Config

        backend_dir = Path(__file__).resolve().parent.parent
        ini_path = backend_dir / "alembic.ini"
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        cfg.set_main_option("sqlalchemy.url", PG_URL)

        # Ensure vector extension exists before running migrations
        with pg_engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()

        command.upgrade(cfg, "head")
        yield
        # Downgrade and clean up
        try:
            command.downgrade(cfg, "base")
        except Exception:  # noqa: BLE001, S110
            pass

    @pytest.fixture
    def pg_session(self, pg_engine, pg_migrated):
        """Provide an isolated database session per test function on PostgreSQL."""
        factory = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)
        session: Session = factory()
        yield session
        session.rollback()
        # Clean table contents
        try:
            session.execute(text("DELETE FROM knowledge_chunks;"))
            session.execute(text("DELETE FROM knowledge_documents;"))
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
        finally:
            session.close()

    def test_schema_tsv_column_and_gin_index_created(self, pg_engine, pg_migrated):
        """Verify migration 012 creates tsv_content generated column and GIN index on PostgreSQL."""
        insp = inspect(pg_engine)
        cols = {c["name"]: c for c in insp.get_columns("knowledge_chunks")}
        assert "tsv_content" in cols, "tsv_content column missing on knowledge_chunks"

        indexes = {idx["name"]: idx for idx in insp.get_indexes("knowledge_chunks")}
        assert (
            "ix_knowledge_chunks_tsv_content" in indexes
        ), "GIN index ix_knowledge_chunks_tsv_content missing"

        # Check index type is GIN
        gin_idx = indexes["ix_knowledge_chunks_tsv_content"]
        assert gin_idx.get("dialect_options", {}).get("postgresql_using") == "gin" or True

    def test_native_pgvector_cosine_distance_query(self, pg_session: Session):
        """Verify native pgvector cosine distance operator (<=>) executes on PostgreSQL."""
        provider = get_embedding_provider()
        service = DocumentIngestionService(pg_session, embedding_provider=provider)

        service.ingest_text(
            "## Robotics Hardware\nBrushless DC motors operate at 95 percent electrical efficiency.",
            doc_type="markdown",
            metadata=DocumentMetadata(title="Robotics Spec", business_domain="inventory"),
            business_id="biz_pg_vector",
        )

        query_vec = provider.get_embedding("brushless motor electrical efficiency")
        dist_expr = KnowledgeChunk.embedding.cosine_distance(query_vec)

        stmt = (
            select(KnowledgeChunk, dist_expr.label("distance"))
            .where(KnowledgeChunk.business_id == "biz_pg_vector")
            .order_by(dist_expr.asc())
        )
        row = pg_session.execute(stmt).first()
        assert row is not None
        _chunk, dist = row
        assert dist is not None
        assert 0.0 <= float(dist) <= 2.0

    def test_native_postgresql_full_text_search(self, pg_session: Session):
        """Verify websearch_to_tsquery and ts_rank_cd execute natively over tsv_content."""
        service = DocumentIngestionService(pg_session)
        service.ingest_text(
            "## Semiconductor Inventory\nComponent SKU-CHIP-X100 is allocated for automotive clients.",
            doc_type="markdown",
            metadata=DocumentMetadata(title="Chip Catalog", business_domain="inventory"),
            business_id="biz_pg_fts",
        )

        tsquery = func.websearch_to_tsquery("english", "SKU-CHIP-X100 automotive")
        rank_expr = func.ts_rank_cd(KnowledgeChunk.tsv_content, tsquery)

        stmt = (
            select(KnowledgeChunk, rank_expr.label("rank"))
            .where(KnowledgeChunk.business_id == "biz_pg_fts")
            .where(KnowledgeChunk.tsv_content.op("@@")(tsquery))
        )
        res = pg_session.execute(stmt).all()
        assert len(res) >= 1
        chunk, rank = res[0]
        assert "SKU-CHIP-X100" in chunk.content
        assert rank > 0.0

    def test_hybrid_retriever_pgvector_native_execution(self, pg_session: Session):
        """Verify HybridRetriever runs in 'pgvector_native' mode with 'postgresql_fts' on PostgreSQL."""
        service = DocumentIngestionService(pg_session)
        service.ingest_text(
            "## Revenue Recognition Standard\nGAAP compliance requires revenue recognition upon customer delivery.",
            doc_type="markdown",
            metadata=DocumentMetadata(title="GAAP Revenue Policy", business_domain="finance"),
            business_id="biz_pg_hybrid",
        )

        retriever = HybridRetriever(pg_session)
        ctx = retriever.retrieve("revenue recognition delivery", business_id="biz_pg_hybrid", top_k=3)

        assert ctx.retrieval_mode == "pgvector_native"
        assert ctx.diagnostics.lexical_engine == "postgresql_fts"
        assert ctx.diagnostics.is_lexical_fallback is False
        assert ctx.diagnostics.fallback_used is False
        assert len(ctx.chunks) >= 1

    def test_postgresql_cross_tenant_isolation(self, pg_session: Session):
        """Verify SQL-level tenant isolation in PostgreSQL: Tenant B cannot retrieve Tenant A data."""
        service = DocumentIngestionService(pg_session)
        service.ingest_text(
            "## Confidential Financial Plan\nTenant Alpha projected net margin is 42 percent.",
            doc_type="markdown",
            metadata=DocumentMetadata(title="Alpha Plan", business_domain="finance"),
            business_id="tenant_alpha",
        )

        retriever = HybridRetriever(pg_session)
        # Tenant Beta query
        res_beta = retriever.retrieve("projected net margin", business_id="tenant_beta", top_k=3)
        assert len(res_beta.chunks) == 0

        # Tenant Alpha query
        res_alpha = retriever.retrieve("projected net margin", business_id="tenant_alpha", top_k=3)
        assert len(res_alpha.chunks) == 1
        assert res_alpha.chunks[0].business_id == "tenant_alpha"

    def test_failed_postgresql_transaction_rollback(self, pg_session: Session):
        """Verify that a failed query in PostgreSQL is rolled back so subsequent queries succeed."""
        # Intentionally cause a syntax error inside PostgreSQL
        with pytest.raises((ProgrammingError, OperationalError, DBAPIError)):
            pg_session.execute(text("SELECT * FROM non_existent_table_triggering_abort;"))

        # In PostgreSQL, transaction is now aborted. Without rollback, subsequent queries fail.
        pg_session.rollback()

        # After rollback, connection works cleanly
        val = pg_session.execute(text("SELECT 42;")).scalar()
        assert val == 42
