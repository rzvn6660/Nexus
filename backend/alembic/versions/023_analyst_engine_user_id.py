"""NEXUS Analyst Engine: AnalysisRun user_id column migration.

Revision ID: 023_analyst_engine_user_id
Revises: 022_pulse_reporting_and_automation
Create Date: 2026-11-05

Adds:
- analysis_runs.user_id VARCHAR(36) with index for user-scoped auditability.
"""

from typing import Sequence, Union
from alembic import op, context
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "023_analyst_engine_user_id"
down_revision: Union[str, None] = "022_pulse_reporting_and_automation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [c["name"] for c in insp.get_columns("analysis_runs")]

    if "user_id" not in columns:
        op.add_column("analysis_runs", sa.Column("user_id", sa.String(36), nullable=True))
        op.create_index("ix_analysis_runs_user_id", "analysis_runs", ["user_id"])


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [c["name"] for c in insp.get_columns("analysis_runs")]

    if "user_id" in columns:
        op.drop_index("ix_analysis_runs_user_id", table_name="analysis_runs")
        op.drop_column("analysis_runs", "user_id")
