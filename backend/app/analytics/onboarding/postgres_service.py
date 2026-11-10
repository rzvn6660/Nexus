"""PostgreSQL Relational Database Onboarding Service.

Provides secure, tenant-isolated extraction, schema inspection, preview,
and ingestion from external PostgreSQL databases into NEXUS canonical models.
Enforces strict SQL injection prevention, connection timeouts, and
tenant boundary verification.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.customer import Customer
from app.models.sale import Sale

logger = get_logger(__name__)

SAFE_IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class PostgreSQLOnboardingService:
    """Service for onboarding data from external PostgreSQL relational databases."""

    @staticmethod
    def _build_connection_string(
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        sslmode: str = "prefer",
    ) -> str:
        """Construct a safe connection string with timeout controls."""
        return (
            f"host={host} port={port} dbname={database} user={user} "
            f"password={password} sslmode={sslmode} connect_timeout=5"
        )

    @classmethod
    def test_connection(
        cls,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        sslmode: str = "prefer",
    ) -> dict[str, Any]:
        """Test reachability and authentication to target PostgreSQL database."""
        conn_str = cls._build_connection_string(host, port, database, user, password, sslmode)
        try:
            with psycopg.connect(conn_str) as conn, conn.cursor() as cur:
                cur.execute("SELECT version();")
                row = cur.fetchone()
                server_version = row[0] if row else "Unknown"
                return {
                    "success": True,
                    "server_version": server_version,
                    "database": database,
                    "host": host,
                    "port": port,
                    "message": "Connection established successfully.",
                }
        except Exception as exc:
            logger.warning(f"PostgreSQL connection test failed: {exc}")
            return {
                "success": False,
                "error": str(exc),
                "database": database,
                "host": host,
                "port": port,
            }

    @classmethod
    def inspect_tables(
        cls,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        sslmode: str = "prefer",
    ) -> list[dict[str, Any]]:
        """List user tables and their column schemas."""
        conn_str = cls._build_connection_string(host, port, database, user, password, sslmode)
        tables: list[dict[str, Any]] = []
        try:
            with psycopg.connect(conn_str) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT table_schema, table_name
                        FROM information_schema.tables
                        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                          AND table_type = 'BASE TABLE'
                        ORDER BY table_schema, table_name;
                        """
                    )
                    table_rows = cur.fetchall()

                    for schema_name, table_name in table_rows:
                        cur.execute(
                            """
                            SELECT column_name, data_type, is_nullable
                            FROM information_schema.columns
                            WHERE table_schema = %s AND table_name = %s
                            ORDER BY ordinal_position;
                            """,
                            (schema_name, table_name),
                        )
                        cols = [
                            {
                                "name": c[0],
                                "data_type": c[1],
                                "is_nullable": c[2] == "YES",
                            }
                            for c in cur.fetchall()
                        ]
                        tables.append(
                            {
                                "schema": schema_name,
                                "table": table_name,
                                "full_name": f"{schema_name}.{table_name}" if schema_name != "public" else table_name,
                                "columns": cols,
                                "column_count": len(cols),
                            }
                        )
            return tables
        except Exception as exc:
            logger.error(f"PostgreSQL schema inspection error: {exc}")
            raise ValueError(f"Failed to inspect PostgreSQL schema: {exc}")

    @classmethod
    def preview_table(
        cls,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        table_name: str,
        schema_name: str = "public",
        limit: int = 15,
        sslmode: str = "prefer",
    ) -> dict[str, Any]:
        """Fetch preview rows from target table with strict identifier validation."""
        if not SAFE_IDENTIFIER_REGEX.match(table_name) or not SAFE_IDENTIFIER_REGEX.match(schema_name):
            raise ValueError(f"Invalid table or schema name identifier: {schema_name}.{table_name}")

        conn_str = cls._build_connection_string(host, port, database, user, password, sslmode)
        try:
            with psycopg.connect(conn_str) as conn, conn.cursor() as cur:
                # Count total rows
                cur.execute(
                    sql.SQL('SELECT COUNT(*) FROM {}.{};').format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                    )
                )
                count_row = cur.fetchone()
                total_rows = count_row[0] if count_row else 0

                # Fetch sample
                cur.execute(
                    sql.SQL('SELECT * FROM {}.{} LIMIT %s;').format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                    ),
                    (min(limit, 100),),
                )
                col_names = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchall()

                # Convert rows to serializable dicts
                sample_rows: list[dict[str, Any]] = []
                for row in rows:
                    row_dict = {}
                    for i, val in enumerate(row):
                        if isinstance(val, (datetime, Decimal)):
                            row_dict[col_names[i]] = str(val)
                        else:
                            row_dict[col_names[i]] = val
                    sample_rows.append(row_dict)

                return {
                    "schema": schema_name,
                    "table": table_name,
                    "total_rows": total_rows,
                    "columns": col_names,
                    "sample_rows": sample_rows,
                }
        except Exception as exc:
            logger.error(f"PostgreSQL table preview error: {exc}")
            raise ValueError(f"Failed to preview table {schema_name}.{table_name}: {exc}")

    @classmethod
    def ingest_table_to_canonical(
        cls,
        db: Session,
        business_id: str,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        table_name: str,
        target_entity: str,
        column_mapping: dict[str, str],
        schema_name: str = "public",
        max_rows: int = 50_000,
        sslmode: str = "prefer",
    ) -> dict[str, Any]:
        """
        Extract records from external PostgreSQL table and ingest into NEXUS canonical models.
        Enforces tenant isolation, idempotency, duplicate protection, and rejected record tracking.
        """
        if not SAFE_IDENTIFIER_REGEX.match(table_name) or not SAFE_IDENTIFIER_REGEX.match(schema_name):
            raise ValueError(f"Invalid table or schema name identifier: {schema_name}.{table_name}")

        # Import Authorization Verification: Ensure written merchant authorization before processing real merchant data
        auth_ref = column_mapping.get("written_authorization_ref")
        try:
            from app.services.tenant_certification_policy import TenantCertificationPolicy
            TenantCertificationPolicy.assert_merchant_import_authorized(
                business_id=business_id,
                session=db,
                authorization_ref=auth_ref,
            )
        except PermissionError as auth_err:
            raise PermissionError(str(auth_err))

        conn_str = cls._build_connection_string(host, port, database, user, password, sslmode)

        inserted_count = 0
        skipped_duplicates = 0
        rejected_records: list[dict[str, Any]] = []

        try:
            with psycopg.connect(conn_str) as conn, conn.cursor() as cur:
                cur.execute(
                    sql.SQL('SELECT * FROM {}.{} LIMIT %s;').format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                    ),
                    (max_rows,),
                )
                col_names = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchall()

            col_index = {col: i for i, col in enumerate(col_names)}

            # Ingest by target entity
            if target_entity == "Sale":
                date_col = column_mapping.get("date")
                amount_col = column_mapping.get("amount")
                order_num_col = column_mapping.get("order_number") or column_mapping.get("transaction_number")
                cust_code_col = column_mapping.get("customer_code")
                status_col = column_mapping.get("status")

                if not date_col or not amount_col:
                    raise ValueError("Mapping requires at least 'date' and 'amount' fields for Sale entity.")

                # Cache existing customers for this business
                existing_customers = {
                    c.customer_code: c.id
                    for c in db.execute(
                        select(Customer).where(Customer.business_id == business_id)
                    ).scalars().all()
                }

                # Query existing transaction numbers to ensure idempotency
                existing_tx_nums = set(
                    db.execute(
                        select(Sale.transaction_number).where(Sale.business_id == business_id)
                    ).scalars().all()
                )
                staged_tx_dates: list[datetime] = []

                for r_idx, row in enumerate(rows):
                    raw_order_num = (
                        str(row[col_index[order_num_col]]).strip()
                        if order_num_col and order_num_col in col_index and row[col_index[order_num_col]] is not None
                        else f"PG-{table_name}-{r_idx + 1}"
                    )

                    if raw_order_num in existing_tx_nums:
                        skipped_duplicates += 1
                        continue

                    raw_amount = row[col_index[amount_col]] if amount_col in col_index else None
                    if raw_amount is None:
                        rejected_records.append({
                            "row_index": r_idx,
                            "reason": "Missing transaction amount",
                            "data": raw_order_num,
                        })
                        continue

                    try:
                        clean_amount = Decimal(str(raw_amount).replace("$", "").replace(",", "").strip())
                    except (InvalidOperation, ValueError, TypeError):
                        rejected_records.append({
                            "row_index": r_idx,
                            "reason": f"Invalid numerical amount: {raw_amount}",
                            "data": raw_order_num,
                        })
                        continue

                    raw_date = row[col_index[date_col]] if date_col in col_index else None
                    if isinstance(raw_date, datetime):
                        tx_date = raw_date
                    elif isinstance(raw_date, str):
                        try:
                            tx_date = datetime.fromisoformat(raw_date)
                        except (ValueError, TypeError):
                            tx_date = datetime.now(UTC)
                    else:
                        tx_date = datetime.now(UTC)

                    # Customer resolution
                    raw_cust_code = (
                        str(row[col_index[cust_code_col]]).strip()
                        if cust_code_col and cust_code_col in col_index and row[col_index[cust_code_col]] is not None
                        else None
                    )

                    customer_id: int | None = None
                    if raw_cust_code:
                        if raw_cust_code in existing_customers:
                            customer_id = existing_customers[raw_cust_code]
                        else:
                            # Auto-create customer under tenant isolation
                            new_cust = Customer(
                                business_id=business_id,
                                customer_code=raw_cust_code,
                                name=f"Customer {raw_cust_code}",
                                email=f"{raw_cust_code.lower()}@pg-import.nexus",
                                city="Unknown",
                                customer_segment="Retail",
                                acquisition_date=tx_date.date(),
                            )
                            db.add(new_cust)
                            db.flush()
                            existing_customers[raw_cust_code] = new_cust.id
                            customer_id = new_cust.id
                    else:
                        allow_anonymous = (
                            column_mapping.get("allow_anonymous_customer") in (True, "true", "True", 1)
                            or column_mapping.get("allow_anonymous") in (True, "true", "True", 1)
                        )
                        policy_approver = (
                            column_mapping.get("anonymous_policy_approved_by")
                            or column_mapping.get("approved_by")
                        )

                        if allow_anonymous and policy_approver:
                            # Audited manager-approved policy
                            anon_code = f"ANON_{business_id[:8].upper()}"
                            if anon_code not in existing_customers:
                                anon_cust = Customer(
                                    business_id=business_id,
                                    customer_code=anon_code,
                                    name="Audited Anonymous Store Checkout",
                                    email=f"anonymous.{business_id[:8]}@nexus.local",
                                    city="Unknown",
                                    customer_segment="Retail",
                                    acquisition_date=tx_date.date(),
                                )
                                db.add(anon_cust)
                                db.flush()
                                existing_customers[anon_code] = anon_cust.id
                            customer_id = existing_customers[anon_code]
                        else:
                            # Silent anonymous/unmapped assignment is prohibited. Quarantine unresolved row.
                            rejected_records.append({
                                "row_index": r_idx,
                                "reason": (
                                    "Unresolved customer: customer identifier is missing and no audited anonymous policy "
                                    "is approved ('allow_anonymous_customer'=True and 'anonymous_policy_approved_by'=<manager>). Row quarantined."
                                ),
                                "data": raw_order_num,
                                "quarantined": True,
                            })
                            continue

                    sale_status = "completed"
                    if status_col and status_col in col_index and row[col_index[status_col]]:
                        sale_status = str(row[col_index[status_col]]).lower().strip()

                    new_sale = Sale(
                        business_id=business_id,
                        transaction_number=raw_order_num,
                        customer_id=customer_id,
                        transaction_date=tx_date,
                        status=sale_status,
                        subtotal=clean_amount,
                        discount_amount=Decimal("0.00"),
                        tax_amount=Decimal("0.00"),
                        total_amount=clean_amount,
                    )
                    db.add(new_sale)
                    existing_tx_nums.add(raw_order_num)
                    staged_tx_dates.append(tx_date)
                    inserted_count += 1

                # Phase 1F.2: Authoritative Watermark Management & Backfill Invalidation
                if inserted_count > 0 and staged_tx_dates:
                    try:
                        from uuid import uuid4

                        from app.services.watermark_service import WatermarkService
                        source_id = f"pg_{schema_name}_{table_name}"
                        job_id = f"pg_job_{uuid4().hex[:8]}"
                        WatermarkService.detect_backfill_and_handle(
                            session=db,
                            business_id=business_id,
                            source_id=source_id,
                            transaction_dates=staged_tx_dates,
                            job_id=job_id,
                        )
                        # Record import completion with distinct governance states:
                        # - IMPORT_COMPLETED and LATEST_OBSERVED_DATE
                        # - Retains SOURCE_COMPLETENESS_UNVERIFIED (provisional) until authoritative period close
                        # - Never manufactures PERIOD_CLOSE_CERTIFIED automatically
                        WatermarkService.record_import_completion(
                            session=db,
                            business_id=business_id,
                            source_id=source_id,
                            transaction_dates=staged_tx_dates,
                            job_id=job_id,
                            metadata_json={
                                "table_name": table_name,
                                "schema_name": schema_name,
                                "rows_persisted": inserted_count,
                            },
                        )
                    except Exception as wm_exc:  # noqa: BLE001
                        logger.debug("PostgreSQL onboarding watermark lifecycle notice: %s", wm_exc)

                db.commit()

            return {
                "success": True,
                "target_entity": target_entity,
                "total_rows_read": len(rows),
                "inserted_count": inserted_count,
                "rows_ingested": inserted_count,
                "records_persisted": inserted_count,
                "skipped_duplicates": skipped_duplicates,
                "rejected_count": len(rejected_records),
                "rejected_records": rejected_records[:20],
                "readiness_status": "VERIFIED" if inserted_count > 0 else "DIAGNOSTIC_ONLY",
            }
        except Exception as exc:
            db.rollback()
            logger.error(f"PostgreSQL ingestion failed: {exc}")
            raise ValueError(f"PostgreSQL ingestion failed: {exc}")
