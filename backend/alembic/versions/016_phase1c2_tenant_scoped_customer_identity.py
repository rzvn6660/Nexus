"""Tenant-scoped customer identity uniqueness constraints (Phase 1C.2).

Replaces global single-column UNIQUE constraints on customer_code and email
with composite (business_id, customer_code) and (business_id, email) constraints,
allowing distinct tenants to manage identical customer codes or email addresses
without collisions, while preserving intra-tenant uniqueness and referential integrity.

Revision ID: 016_phase1c2_tenant_scoped_customer_identity
Revises: 015_phase29_continuous_intelligence
Create Date: 2026-10-28 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016_phase1c2_tenant_scoped_customer_identity"
down_revision: str | None = "015_phase29_continuous_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("customers"):
        raise RuntimeError(
            "Migration 016 failed: table 'customers' does not exist. "
            "Ensure core retail schema (001_phase2_retail_schema) has been applied."
        )

    customer_cols = {c["name"] for c in insp.get_columns("customers")}
    if "business_id" not in customer_cols:
        raise RuntimeError(
            "Migration 016 failed: column 'business_id' missing from table 'customers'. "
            "Ensure multi-tenant migration (005_phase15_saas_multi_tenancy) has been applied."
        )

    has_code_uq = False
    code_uq_name: str | None = None
    has_email_uq = False
    email_uq_name: str | None = None
    has_composite_code_uq = False
    has_composite_email_uq = False

    for uq in insp.get_unique_constraints("customers"):
        cols = uq.get("column_names") or []
        if cols == ["customer_code"]:
            has_code_uq = True
            code_uq_name = uq.get("name")
        elif cols == ["email"]:
            has_email_uq = True
            email_uq_name = uq.get("name")
        elif cols in (["business_id", "customer_code"], ["customer_code", "business_id"]):
            has_composite_code_uq = True
        elif cols in (["business_id", "email"], ["email", "business_id"]):
            has_composite_email_uq = True

    # Define standard naming convention so SQLite batch mode can locate unnamed constraints
    naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}

    with op.batch_alter_table("customers", naming_convention=naming_convention) as batch_op:
        # Drop legacy global single-column uniqueness constraints if present
        if has_code_uq:
            batch_op.drop_constraint(code_uq_name or "uq_customers_customer_code", type_="unique")
        if has_email_uq:
            batch_op.drop_constraint(email_uq_name or "uq_customers_email", type_="unique")

        # Create composite tenant-scoped uniqueness constraints if not already present
        if not has_composite_code_uq:
            batch_op.create_unique_constraint(
                "uq_customers_business_customer_code",
                ["business_id", "customer_code"],
            )
        if not has_composite_email_uq:
            batch_op.create_unique_constraint(
                "uq_customers_business_email",
                ["business_id", "email"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("customers"):
        raise RuntimeError("Migration 016 downgrade failed: table 'customers' does not exist.")

    has_composite_code_uq = False
    composite_code_name: str | None = None
    has_composite_email_uq = False
    composite_email_name: str | None = None
    has_code_uq = False
    has_email_uq = False

    for uq in insp.get_unique_constraints("customers"):
            cols = uq.get("column_names") or []
            if cols in (["business_id", "customer_code"], ["customer_code", "business_id"]):
                has_composite_code_uq = True
                composite_code_name = uq.get("name")
            elif cols in (["business_id", "email"], ["email", "business_id"]):
                has_composite_email_uq = True
                composite_email_name = uq.get("name")
            elif cols == ["customer_code"]:
                has_code_uq = True
            elif cols == ["email"]:
                has_email_uq = True

    with op.batch_alter_table("customers") as batch_op:
        # Drop composite tenant-scoped uniqueness constraints if present
        if has_composite_code_uq:
            batch_op.drop_constraint(
                composite_code_name or "uq_customers_business_customer_code",
                type_="unique",
            )
        if has_composite_email_uq:
            batch_op.drop_constraint(
                composite_email_name or "uq_customers_business_email",
                type_="unique",
            )

        # Restore legacy global single-column uniqueness constraints if not present
        if not has_code_uq:
            batch_op.create_unique_constraint("uq_customers_customer_code", ["customer_code"])
        if not has_email_uq:
            batch_op.create_unique_constraint("uq_customers_email", ["email"])
