"""Relational SQL Database Connector for tabular enterprise ingestion."""

from typing import Any, Dict, Generator, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.data.connectors.base import BaseConnector


class SQLConnector(BaseConnector):
    """
    Connects to external SQL relational databases (PostgreSQL, MySQL, SQLite)
    to stream tabular data rows deterministically into NEXUS.
    """

    def __init__(self, connection_uri: str, query: str) -> None:
        self.connection_uri = connection_uri
        self.query = query
        self._engine: Optional[Engine] = None

    def connect(self) -> None:
        """Establish database engine pool."""
        if not self._engine:
            self._engine = create_engine(self.connection_uri, pool_pre_ping=True)

    def disconnect(self) -> None:
        """Dispose of engine connection pool."""
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def validate_source(self) -> bool:
        """Verify database connectivity and query syntax via dry run."""
        try:
            self.connect()
            assert self._engine is not None
            with self._engine.connect() as conn:
                # Test query execution with zero rows limit
                test_query = f"SELECT * FROM ({self.query}) AS dry_run_table LIMIT 0"
                conn.execute(text(test_query))
            return True
        except Exception:
            return False

    def read_records(self, limit: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
        """Stream query result rows as column-keyed dictionaries."""
        self.connect()
        assert self._engine is not None
        with self._engine.connect() as conn:
            stmt = text(self.query)
            result = conn.execute(stmt)
            count = 0
            for row in result.mappings():
                yield dict(row)
                count += 1
                if limit and count >= limit:
                    break
