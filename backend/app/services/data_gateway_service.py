"""Deterministic Production Data Gateway Service (Phase 16 Hardened).

Coordinates:
- Secure tenant-isolated storage for tabular business data
- SHA-256 content fingerprinting and idempotent deduplication
- Configurable upload guardrails (file size, row limits, column limits, cell length limits)
- Binary magic-signature inspection (executable/script rejection)
- Multi-encoding resilience (UTF-8, Latin-1, CP1252) and malformed file handling
- Deterministic column profiling (data types, nulls, uniqueness, role classification)
- Negative-value handling (non-penalizing identification of returns, refunds, adjustments)
- 6-dimension data readiness evaluation (Processing, Structure, Quality, Mapping, Time, Analytics)
- High-score override prevention on critical mapping ambiguity
- Durable IngestionJob lifecycle (PENDING, PROCESSING, COMPLETED, FAILED, REQUIRES_REVIEW)
- Idempotent record ingestion into unified NEXUS relational models (Sale, Product, Customer, SaleItem, Inventory, Expense)
"""

import hashlib
import io
import math
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.logging import get_logger
from app.models.customer import Customer
from app.models.expense import Expense
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, IngestionJob, UploadedDataset
from app.schemas.data_gateway import (
    ColumnProfile,
    DataPreviewResponse,
    DataReadinessSummary,
    DateCoverage,
    QualityCheckItem,
    SchemaMappingProposal,
)

logger = get_logger(__name__)


class DataGatewayService:
    """Production Data Gateway orchestrating ingestion, profiling, quality, and schema mapping."""

    MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB (reconciled with ingress and tenant storage)
    MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB alias
    MAX_ROWS = 500_000
    MAX_ROW_COUNT = 500_000  # alias
    MAX_COLUMNS = 200
    MAX_CELL_LENGTH = 10_000

    ALLOWED_EXTENSIONS: ClassVar[set[str]] = {".csv", ".xlsx", ".xls"}
    PROHIBITED_EXTENSIONS: ClassVar[set[str]] = {
        ".exe", ".py", ".sh", ".bat", ".bin", ".js", ".html", ".dll",
        ".cmd", ".vbs", ".ps1", ".com", ".scr", ".msi",
    }

    ENTITY_TARGETS: ClassVar[dict[str, Any]] = {
        "Sale": {
            "required": ["date", "amount"],
            "optional": ["customer_code", "order_number", "payment_method", "channel"],
            "patterns": {
                "date": [r"\bdate\b", r"\border_date\b", r"\btransaction_date\b", r"\bcreated_at\b", r"\bsale_date\b"],
                "amount": [r"\bamount\b", r"\brevenue\b", r"\btotal\b", r"\bsales\b", r"\bsubtotal\b", r"\bprice\b"],
                "customer_code": [r"\bcustomer_code\b", r"\bcustomer_id\b", r"\bclient_id\b", r"\bcustomer\b"],
                "order_number": [r"\border_number\b", r"\border_id\b", r"\binvoice\b", r"\binvoice_no\b", r"\btransaction_id\b"],
                "payment_method": [r"\bpayment\b", r"\bpayment_method\b", r"\bpayment_type\b"],
                "channel": [r"\bchannel\b", r"\bstore\b", r"\blocation\b", r"\bsales_channel\b"],
            },
        },
        "Customer": {
            "required": ["customer_code", "name"],
            "optional": ["email", "city", "customer_segment", "acquisition_date"],
            "patterns": {
                "customer_code": [r"\bcustomer_code\b", r"\bcustomer_id\b", r"\bcode\b", r"\bid\b"],
                "name": [r"\bname\b", r"\bcustomer_name\b", r"\bclient_name\b", r"\bfull_name\b"],
                "email": [r"\bemail\b", r"\bemail_address\b"],
                "city": [r"\bcity\b", r"\btown\b", r"\bregion\b"],
                "customer_segment": [r"\bsegment\b", r"\bcustomer_segment\b", r"\btier\b", r"\btype\b"],
                "acquisition_date": [r"\bacquisition_date\b", r"\bjoin_date\b", r"\bsigned_up\b"],
            },
        },
        "Product": {
            "required": ["sku", "name", "selling_price"],
            "optional": ["category", "subcategory", "unit_cost"],
            "patterns": {
                "sku": [r"\bsku\b", r"\bproduct_id\b", r"\bitem_code\b", r"\bcode\b"],
                "name": [r"\bname\b", r"\bproduct_name\b", r"\btitle\b", r"\bitem_name\b"],
                "category": [r"\bcategory\b", r"\bdepartment\b", r"\bgroup\b"],
                "subcategory": [r"\bsubcategory\b", r"\bsub_category\b"],
                "unit_cost": [r"\bunit_cost\b", r"\bcost\b", r"\bpurchase_price\b"],
                "selling_price": [r"\bselling_price\b", r"\bprice\b", r"\bmrp\b", r"\brate\b"],
            },
        },
        "SaleItem": {
            "required": ["sale_id", "product_id", "quantity", "unit_price"],
            "optional": ["discount_amount", "tax_amount", "line_total"],
            "patterns": {
                "sale_id": [r"\bsale_id\b", r"\border_id\b", r"\btransaction_id\b", r"\binvoice_id\b", r"\btransaction_number\b", r"\border_number\b", r"\bsale_ref\b"],
                "product_id": [r"\bproduct_id\b", r"\bsku\b", r"\bitem_id\b", r"\bproduct_sku\b", r"\bproduct_ref\b"],
                "quantity": [r"\bquantity\b", r"\bqty\b", r"\bunits\b", r"\bcount\b"],
                "unit_price": [r"\bunit_price\b", r"\bprice\b", r"\brate\b", r"\bitem_price\b"],
                "discount_amount": [r"\bdiscount\b", r"\bdiscount_amount\b", r"\bpromo\b"],
                "tax_amount": [r"\btax\b", r"\btax_amount\b", r"\bgst\b", r"\bvat\b"],
                "line_total": [r"\bline_total\b", r"\btotal\b", r"\bsubtotal\b", r"\bline_amount\b"],
            },
        },
        "Inventory": {
            "required": ["product_id", "stock_quantity"],
            "optional": ["reorder_threshold", "warehouse"],
            "patterns": {
                "product_id": [r"\bproduct_id\b", r"\bsku\b", r"\bitem_id\b"],
                "stock_quantity": [r"\bstock_quantity\b", r"\bquantity\b", r"\bstock\b", r"\bqty\b", r"\bon_hand\b"],
                "reorder_threshold": [r"\breorder_threshold\b", r"\bmin_stock\b", r"\breorder_level\b"],
                "warehouse": [r"\bwarehouse\b", r"\blocation\b", r"\bbin\b"],
            },
        },
        "Expense": {
            "required": ["expense_date", "category", "amount"],
            "optional": ["description", "vendor"],
            "patterns": {
                "expense_date": [r"\bexpense_date\b", r"\bdate\b", r"\bpayment_date\b"],
                "category": [r"\bcategory\b", r"\bexpense_type\b", r"\baccount\b"],
                "amount": [r"\bamount\b", r"\bcost\b", r"\btotal\b", r"\bprice\b"],
                "description": [r"\bdescription\b", r"\bnotes\b", r"\bmemo\b"],
                "vendor": [r"\bvendor\b", r"\bsupplier\b", r"\bpayee\b"],
            },
        },
    }

    @classmethod
    def sanitize_filename(cls, filename: str) -> str:
        """Sanitize filename against path traversal, null bytes, and malicious characters while supporting Unicode."""
        if not filename:
            return f"upload_{str(uuid4())[:8]}.csv"
        # Strip null bytes and directory traversal separators
        clean = filename.replace("\x00", "").replace("/", "_").replace("\\", "_")
        clean = re.sub(r"\.\.+", ".", clean)
        # Allow alphanumeric, unicode letters, digits, dots, underscores, dashes
        clean = re.sub(r"[^\w.\-]", "_", clean, flags=re.UNICODE).strip("._")
        return clean or f"upload_{str(uuid4())[:8]}.csv"

    @classmethod
    def validate_file_security(cls, filename: str, content_bytes: bytes) -> None:
        """Validate size bounds, extension whitelist, prohibited types, and binary content inspection."""
        if len(content_bytes) > cls.MAX_UPLOAD_BYTES:
            logger.warning(
                "Upload rejected: file size %d bytes exceeds limit for filename='%s'",
                len(content_bytes), filename,
            )
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File size exceeds maximum allowable limit of {cls.MAX_UPLOAD_BYTES // (1024*1024)} MB.",
            )
        if len(content_bytes) == 0:
            logger.warning("Upload rejected: empty file (0 bytes) filename='%s'", filename)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes). Please provide a valid CSV or Excel file containing tabular business data.",
            )

        # Check binary magic signatures (MIME spoofing detection)
        if content_bytes.startswith((b"MZ", b"\x7fELF")):
            logger.warning(
                "SECURITY: Executable binary upload rejected. filename='%s' size=%d bytes",
                filename, len(content_bytes),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Executable binary format rejected.",
            )
        if content_bytes.startswith((b"#!/bin/", b"#!/usr/bin/")):
            logger.warning(
                "SECURITY: Shell script upload rejected. filename='%s' size=%d bytes",
                filename, len(content_bytes),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Shell script execution format rejected.",
            )

        ext = Path(filename).suffix.lower()
        if ext in cls.PROHIBITED_EXTENSIONS or ext not in cls.ALLOWED_EXTENSIONS:
            logger.warning(
                "SECURITY: Prohibited file extension upload rejected. filename='%s' ext='%s'",
                filename, ext,
            )
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file extension '{ext}'. Only CSV (.csv) and Excel (.xlsx, .xls) are permitted.",
            )

    @classmethod
    def read_csv_dataframe(
        cls,
        source: io.BytesIO | bytes | Path | str,
        nrows: int | None = None,
    ) -> pd.DataFrame:
        """
        Read CSV tabular data into a pandas DataFrame using a deliberate, ordered decoding strategy:
        1. 'utf-8-sig': Consumes and strips UTF-8 BOM if present, and decodes valid standard UTF-8.
        2. 'utf-8': Strict standard UTF-8.
        3. 'cp1252': Windows-1252 encoding. Preserves single-byte characters common in Excel/Windows exports,
           including Euro ('€' [0x80]), smart quotes ('“' [0x93], '”' [0x94]), and em-dashes ('—' [0x97]).
           Must precede Latin-1 because Latin-1 (ISO-8859-1) maps 0x80-0x9F to unprintable C1 control codes
           without raising an error, silently masking CP1252 text.
        4. 'latin1': ISO-8859-1 as a documented last-resort fallback for single-byte streams where CP1252 fails
           (e.g. unassigned bytes 0x81, 0x8D, 0x8F, 0x90, 0x9D).

        Encoding & Malformed Input Policy:
        - Strict UTF-8 is the canonical standard for all uploads.
        - Binary streams or files containing NULL bytes (b"\\x00") are rejected immediately with HTTP 400.
        - Syntactic malformations (ragged rows, unclosed quotes, invalid delimiters) raise HTTP 400.
        - Inherent Ambiguity Limitation: Single-byte character streams without out-of-band charset metadata
          cannot be mathematically distinguished from damaged UTF-8 if byte values happen to coincide with
          valid single-byte code points. Downstream strict type validations (dates, decimals) prevent silent
          corruption of core analytical fields.

        Raises HTTPException(400) if content cannot be parsed or decoded.
        """
        if isinstance(source, bytes):
            raw_bytes = source
        elif isinstance(source, io.BytesIO):
            raw_bytes = source.getvalue()
        else:
            path = Path(source)
            if not path.exists():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Dataset file is no longer available on storage.",
                )
            raw_bytes = path.read_bytes()

        # Reject binary streams and null-byte corrupted content immediately
        if b"\x00" in raw_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed CSV content: NULL byte or binary stream detected.",
            )

        df: pd.DataFrame | None = None
        encodings = ["utf-8-sig", "utf-8", "cp1252", "latin1"]
        last_error = None

        for enc in encodings:
            try:
                df = pd.read_csv(io.BytesIO(raw_bytes), nrows=nrows, encoding=enc, index_col=False)
                break
            except UnicodeDecodeError as ude:
                last_error = ude
                continue
            except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Malformed CSV content: {str(exc).splitlines()[0]}",
                )

        if df is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to decode CSV content with supported encodings (UTF-8, UTF-8 with BOM, CP1252, Latin-1). Last error: {last_error}",
            )
        return df

    @classmethod
    def save_raw_dataset(
        cls,
        db: Session,
        organization_id: str,
        business_id: str,
        filename: str,
        content: bytes,
    ) -> UploadedDataset:
        """Validate, store securely on disk, and create or retrieve UploadedDataset record idempotently."""
        clean_name = cls.sanitize_filename(filename)
        cls.validate_file_security(clean_name, content)

        # 1. Deterministic Content Hash (SHA-256) for Idempotency
        content_hash = hashlib.sha256(content).hexdigest()

        # Idempotency check: If an identical dataset already exists for this business, return it
        existing_dataset = db.execute(
            select(UploadedDataset).where(
                UploadedDataset.business_id == business_id,
                UploadedDataset.content_hash == content_hash,
            )
        ).scalars().first()
        if existing_dataset:
            logger.info(
                "Dataset upload idempotent no-op: business_id=%s existing_dataset_id=%s filename='%s'",
                business_id, existing_dataset.id, clean_name,
            )
            return existing_dataset

        ext = Path(clean_name).suffix.lower()
        df: pd.DataFrame | None = None

        if ext == ".csv":
            df = cls.read_csv_dataframe(content)
        else:
            try:
                df = pd.read_excel(io.BytesIO(content))
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Malformed or corrupted Excel workbook: {str(exc).splitlines()[0]}",
                )

        if df is None or len(df) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded dataset contains 0 data rows. Please ensure your file includes column headers followed by at least one row of data.",
            )
        if len(df) > cls.MAX_ROWS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dataset row count ({len(df)}) exceeds maximum limit of {cls.MAX_ROWS}.",
            )
        if len(df.columns) > cls.MAX_COLUMNS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dataset column count ({len(df.columns)}) exceeds maximum limit of {cls.MAX_COLUMNS}.",
            )

        # Check maximum cell length limit
        for col in df.columns:
            str_lens = df[col].astype(str).str.len()
            if (str_lens > cls.MAX_CELL_LENGTH).any():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cell value in column '{col}' exceeds maximum allowable length of {cls.MAX_CELL_LENGTH} characters.",
                )

        # Profile, audit quality, and infer schema mapping deterministically
        col_profiles, date_coverage = cls.profile_columns(df)
        mapping_proposal = cls.infer_schema_mapping(df, col_profiles)
        quality_summary = cls.evaluate_quality(df, col_profiles, date_coverage, mapping_proposal)

        # Deterministic dataset version tracking for this business and filename
        existing_versions_count = len(
            db.execute(
                select(UploadedDataset.id).where(
                    UploadedDataset.business_id == business_id,
                    UploadedDataset.filename == clean_name,
                )
            ).scalars().all()
        )
        dataset_version = existing_versions_count + 1

        dataset_id = str(uuid4())
        base_dir = Path(getattr(settings, "DATA_DIR", "data"))
        clean_org = re.sub(r"[^a-zA-Z0-9_-]", "_", str(organization_id)).strip("._") or "default_org"
        clean_biz = re.sub(r"[^a-zA-Z0-9_-]", "_", str(business_id)).strip("._") or "default_biz"
        storage_rel_dir = base_dir / "tenants" / clean_org / clean_biz / dataset_id
        storage_file_path = storage_rel_dir / clean_name

        try:
            if not storage_file_path.resolve().is_relative_to(base_dir.resolve()):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security violation: storage path escapes configured storage root.",
                )
        except (ValueError, RuntimeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security violation: invalid storage root path traversal.",
            )

        try:
            storage_rel_dir.mkdir(parents=True, exist_ok=True)
            storage_file_path.write_bytes(content)
        except OSError as exc:
            logger.error("Failed to persist dataset file to persistent volume at %s: %s", storage_rel_dir, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Storage error: unable to save file to persistent volume: {exc}",
            )

        ingestion_status = "PENDING"
        if quality_summary.overall_status in ["REQUIRES_REVIEW", "INSUFFICIENT_DATA"]:
            ingestion_status = "REQUIRES_REVIEW"

        schema_json = {
            "columns": [str(c) for c in df.columns],
            "column_profiles": [cp.model_dump() for cp in col_profiles],
            "date_coverage": date_coverage.model_dump() if date_coverage else None,
            "mapping_proposal": mapping_proposal.model_dump(),
            "ingestion_status": ingestion_status,
            "dimensions": quality_summary.dimensions,
            "dataset_version": dataset_version,
            "source_filename": clean_name,
            "content_hash": content_hash,
        }

        dataset = UploadedDataset(
            id=dataset_id,
            organization_id=organization_id,
            business_id=business_id,
            filename=clean_name,
            file_type=ext.lstrip("."),
            storage_key=str(storage_file_path).replace("\\", "/"),
            file_size_bytes=len(content),
            row_count=len(df),
            column_count=len(df.columns),
            content_hash=content_hash,
            schema_json=schema_json,
            quality_report_json=quality_summary.model_dump(),
            readiness_status=quality_summary.overall_status,
        )
        db.add(dataset)

        # Create persistent IngestionJob tracking upload lifecycle
        initial_job = IngestionJob(
            id=str(uuid4()),
            organization_id=organization_id,
            business_id=business_id,
            dataset_id=dataset_id,
            status=ingestion_status,
            target_entity=mapping_proposal.target_entity,
            started_at=datetime.now(UTC),
            rows_processed=len(df),
        )
        db.add(initial_job)

        # Update business data readiness status
        biz = db.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        if biz:
            biz.data_readiness_status = quality_summary.overall_status
            if quality_summary.can_open_workspace:
                biz.onboarding_step = "completed"

        try:
            db.commit()
            db.refresh(dataset)
        except Exception as db_exc:
            db.rollback()
            try:
                if storage_file_path.exists():
                    storage_file_path.unlink()
                if storage_rel_dir.exists() and not any(storage_rel_dir.iterdir()):
                    storage_rel_dir.rmdir()
            except OSError as cleanup_err:
                logger.warning("Failed to clean up unindexed storage file %s: %s", storage_file_path, cleanup_err)
            raise db_exc

        logger.info(
            "Dataset upload accepted: business_id=%s dataset_id=%s filename='%s' "
            "rows=%d cols=%d readiness=%s",
            business_id, dataset_id, clean_name,
            len(df), len(df.columns), quality_summary.overall_status,
        )
        return dataset

    @classmethod
    def profile_columns(cls, df: pd.DataFrame) -> tuple[list[ColumnProfile], DateCoverage | None]:
        """Compute deterministic profiling for every column in the dataframe."""
        row_count = len(df)
        profiles: list[ColumnProfile] = []
        date_coverage: DateCoverage | None = None

        for col in df.columns:
            series = df[col]
            null_count = int(series.isnull().sum())
            null_pct = round((null_count / row_count) * 100, 2)
            unique_count = int(series.nunique(dropna=True))
            uniqueness_ratio = round(unique_count / row_count, 4) if row_count > 0 else 0.0

            clean_series = series.dropna()
            sample_vals = [
                str(v) if isinstance(v, (datetime, date, pd.Timestamp)) else (None if pd.isna(v) else v)
                for v in clean_series.head(5).tolist()
            ]

            # Inferred Type & Role
            col_lower = str(col).lower().strip()
            data_type = "string"
            role = "dimension"
            suspicious = None

            # Test DateTime
            is_date = False
            if any(k in col_lower for k in ["date", "time", "created", "timestamp", "period", "day"]):
                try:
                    dt_parsed = pd.to_datetime(clean_series, errors="coerce").dropna()
                    if len(dt_parsed) > (0.6 * len(clean_series)):
                        data_type = "datetime"
                        role = "date"
                        is_date = True
                        if not date_coverage or len(dt_parsed) > date_coverage.total_valid_dates:
                            date_coverage = DateCoverage(
                                column=str(col),
                                min_date=dt_parsed.min().strftime("%Y-%m-%d"),
                                max_date=dt_parsed.max().strftime("%Y-%m-%d"),
                                total_valid_dates=len(dt_parsed),
                                estimated_granularity="daily" if (dt_parsed.max() - dt_parsed.min()).days > 7 else "irregular",
                            )
                except Exception:  # noqa: BLE001, S110
                    pass

            # Test Numeric
            if not is_date:
                numeric_parsed = pd.to_numeric(clean_series, errors="coerce").dropna()
                if len(numeric_parsed) > (0.8 * len(clean_series)):
                    if (numeric_parsed % 1 == 0).all():
                        data_type = "integer"
                    else:
                        data_type = "float"

                    # Classify Role: measure vs identifier
                    if any(k in col_lower for k in ["price", "amount", "revenue", "cost", "total", "qty", "quantity", "rate", "discount", "margin", "tax"]):
                        role = "measure"
                    elif "id" in col_lower or "code" in col_lower or "sku" in col_lower or (uniqueness_ratio > 0.85 and row_count > 10):
                        role = "identifier"
                    else:
                        role = "measure"

                    # Check for negative measures: note returns/refunds/adjustments without hard penalization
                    if any(k in col_lower for k in ["price", "amount", "revenue", "qty", "quantity"]):
                        neg_count = int((numeric_parsed < 0).sum())
                        if neg_count > 0:
                            neg_pct = (neg_count / len(numeric_parsed)) * 100
                            suspicious = f"Negative values detected in {col_lower} ({neg_count} records, {neg_pct:.1f}%). May represent refunds, returns, or adjustments."
                else:
                    # String / Categorical / ID
                    if any(k in col_lower for k in ["id", "code", "sku", "uuid", "key"]) or (uniqueness_ratio > 0.85 and row_count > 10 and not any(k in col_lower for k in ["name", "title", "desc", "description", "city", "country", "category"])):
                        role = "identifier"
                    else:
                        role = "dimension"

            profiles.append(
                ColumnProfile(
                    name=str(col),
                    data_type=data_type,
                    null_count=null_count,
                    null_percentage=null_pct,
                    unique_count=unique_count,
                    uniqueness_ratio=uniqueness_ratio,
                    sample_values=sample_vals,
                    role=role,
                    suspicious_format=suspicious,
                )
            )

        return profiles, date_coverage

    @classmethod
    def evaluate_quality(
        cls,
        df: pd.DataFrame,
        col_profiles: list[ColumnProfile],
        date_coverage: DateCoverage | None,
        mapping_proposal: SchemaMappingProposal,
    ) -> DataReadinessSummary:
        """
        Deterministic, audit-ready data readiness calculation (0 - 100 points) across 6 governance dimensions:
        1. Processing: File integrity & format parsing
        2. Structure: Row/column cardinality & cell bounds
        3. Data Quality: Completeness, nulls, duplicates
        4. Business Mapping: Target entity recognition & required field coverage
        5. Time Coverage: Historical date continuity
        6. Analytics Availability: Measures and dimensional keys ready for agent queries
        """
        row_count = len(df)
        score = 100
        checks: list[QualityCheckItem] = []
        action_items: list[str] = []
        dimensions: dict[str, str] = {
            "processing": "PASSED",
            "structure": "PASSED",
            "data_quality": "PASSED",
            "business_mapping": "PASSED",
            "time_coverage": "PASSED",
            "analytics_availability": "PASSED",
        }

        # 1. Processing Dimension
        checks.append(QualityCheckItem(
            check_name="file_processing",
            severity="PASS",
            message=f"Dataset parsed cleanly ({row_count} rows, {len(df.columns)} columns).",
            deducted_points=0,
        ))

        # 2. Structure Dimension
        if row_count < 3:
            dimensions["structure"] = "INSUFFICIENT"
            score -= 20
            checks.append(QualityCheckItem(
                check_name="row_cardinality",
                severity="ERROR",
                message=f"Dataset has only {row_count} rows. At least 3 historical rows are required.",
                deducted_points=20,
            ))
            action_items.append("Provide a dataset with at least 3 transactions or records.")
        else:
            checks.append(QualityCheckItem(
                check_name="row_cardinality",
                severity="PASS",
                message=f"Sufficient row volume ({row_count} rows).",
                deducted_points=0,
            ))

        # 3. Time Coverage Dimension
        if not date_coverage:
            dimensions["time_coverage"] = "WARNING"
            score -= 15
            checks.append(QualityCheckItem(
                check_name="temporal_coverage",
                severity="WARNING",
                message="No valid date or timestamp column detected for historical time-series analytics.",
                deducted_points=15,
            ))
            action_items.append("Ensure dataset includes order_date, transaction_date, or timestamp.")
        else:
            checks.append(QualityCheckItem(
                check_name="temporal_coverage",
                severity="PASS",
                message=f"Date coverage verified: {date_coverage.min_date} to {date_coverage.max_date} ({date_coverage.total_valid_dates} records).",
                deducted_points=0,
            ))

        # 4. Key Identifier & Analytics Availability Dimension
        has_identifier = any(cp.role == "identifier" for cp in col_profiles)
        has_measure = any(cp.role == "measure" for cp in col_profiles)
        if not has_identifier:
            dimensions["analytics_availability"] = "WARNING"
            score -= 15
            checks.append(QualityCheckItem(
                check_name="primary_identifier",
                severity="WARNING",
                message="No unique primary key or code column identified.",
                deducted_points=15,
            ))
            action_items.append("Add unique identifiers for orders, customers, or SKUs.")
        else:
            checks.append(QualityCheckItem(
                check_name="primary_identifier",
                severity="PASS",
                message="Primary identifier columns detected.",
                deducted_points=0,
            ))

        # 5. Missing Values & Completeness (Data Quality Dimension)
        high_null_cols = [cp.name for cp in col_profiles if cp.null_percentage > 20.0 and cp.role in ["measure", "identifier"]]
        if high_null_cols:
            dimensions["data_quality"] = "WARNING"
            score -= 10
            checks.append(QualityCheckItem(
                check_name="null_completeness",
                severity="WARNING",
                message=f"Columns with >20% missing values: {', '.join(high_null_cols)}",
                deducted_points=10,
            ))
            action_items.append(f"Review and populate missing values for: {', '.join(high_null_cols)}")
        else:
            checks.append(QualityCheckItem(
                check_name="null_completeness",
                severity="PASS",
                message="Column completeness within acceptable tolerance (<20% nulls).",
                deducted_points=0,
            ))

        # 6. Duplicate Rows (Data Quality Dimension)
        dup_count = int(df.duplicated().sum())
        if dup_count > 0:
            dup_pct = (dup_count / row_count) * 100
            if dup_pct > 1.0:
                dimensions["data_quality"] = "WARNING"
                score -= 10
                checks.append(QualityCheckItem(
                    check_name="duplicate_rows",
                    severity="WARNING",
                    message=f"Detected {dup_count} duplicate rows ({dup_pct:.1f}% of dataset).",
                    deducted_points=10,
                ))
                action_items.append("Deduplicate identical records before analytical processing.")
        else:
            checks.append(QualityCheckItem(
                check_name="duplicate_rows",
                severity="PASS",
                message="Zero duplicate rows detected.",
                deducted_points=0,
            ))

        # 7. Commercial Returns / Refunds / Negative Measures (Informational Check)
        suspicious_list = [cp.suspicious_format for cp in col_profiles if cp.suspicious_format]
        if suspicious_list:
            checks.append(QualityCheckItem(
                check_name="commercial_adjustments",
                severity="INFO",
                message="; ".join(suspicious_list),
                deducted_points=0,  # Do not penalize valid commercial returns/adjustments
            ))
        else:
            checks.append(QualityCheckItem(
                check_name="commercial_adjustments",
                severity="PASS",
                message="No negative adjustments or returns flagged.",
                deducted_points=0,
            ))

        # 8. Business Mapping Dimension
        if mapping_proposal.status == "REQUIRES_REVIEW" or mapping_proposal.missing_required_fields:
            dimensions["business_mapping"] = "REQUIRES_REVIEW"
            checks.append(QualityCheckItem(
                check_name="schema_mapping_fidelity",
                severity="WARNING",
                message=f"Ambiguous mapping for {mapping_proposal.target_entity}. Missing required fields: {mapping_proposal.missing_required_fields or 'None'}.",
                deducted_points=10,
            ))
            score -= 10
        else:
            checks.append(QualityCheckItem(
                check_name="schema_mapping_fidelity",
                severity="PASS",
                message=f"Core entity {mapping_proposal.target_entity} successfully mapped with confidence {mapping_proposal.confidence_score}.",
                deducted_points=0,
            ))

        clamped_score = max(0, min(100, score))

        # Strict Readiness Hierarchy: Critical mapping ambiguity or lack of rows PREVENTS automatic READY
        if row_count < 3:
            overall_status = "INSUFFICIENT_DATA"
            can_open = False
        elif mapping_proposal.status == "REQUIRES_REVIEW" or len(mapping_proposal.missing_required_fields) > 0:
            overall_status = "REQUIRES_REVIEW"
            can_open = False
        elif clamped_score >= 80 and date_coverage is not None and has_measure:
            overall_status = "READY"
            can_open = True
        elif clamped_score >= 60:
            overall_status = "READY_WITH_WARNINGS"
            can_open = True
        else:
            overall_status = "REQUIRES_REVIEW"
            can_open = False

        return DataReadinessSummary(
            overall_status=overall_status,
            readiness_score=clamped_score,
            dimensions=dimensions,
            score_breakdown=checks,
            can_open_workspace=can_open,
            action_items=action_items,
        )

    @classmethod
    def infer_schema_mapping(cls, df: pd.DataFrame, col_profiles: list[ColumnProfile]) -> SchemaMappingProposal:
        """Infer target entity and column mappings using deterministic pattern matching."""
        best_entity = "Sale"
        best_score = -1.0
        best_mapping: dict[str, str] = {}
        best_missing: list[str] = []

        for entity_name, spec in cls.ENTITY_TARGETS.items():
            matched_fields: dict[str, str] = {}
            patterns = spec["patterns"]

            for target_field, pat_list in patterns.items():
                for actual_col in df.columns:
                    if str(actual_col) in matched_fields:
                        continue
                    col_str = str(actual_col).lower().strip()
                    tokens = set(re.split(r"[^a-z0-9]+", col_str))
                    matches = False
                    for p in pat_list:
                        raw_kw = p.replace(r"\b", "").strip()
                        if raw_kw in tokens or raw_kw in col_str or re.search(p, col_str):
                            matches = True
                            break
                    if matches:
                        matched_fields[str(actual_col)] = target_field
                        break

            req_matched = sum(1 for rf in spec["required"] if rf in matched_fields.values())
            missing_req = [rf for rf in spec["required"] if rf not in matched_fields.values()]
            confidence = (req_matched / len(spec["required"])) * 0.7 + (len(matched_fields) / (len(spec["required"]) + len(spec["optional"]))) * 0.3

            if confidence > best_score:
                best_score = confidence
                best_entity = entity_name
                best_mapping = matched_fields
                best_missing = missing_req

        status_str = "MAPPED" if best_score >= 0.75 and not best_missing else "REQUIRES_REVIEW"
        unmapped = [str(c) for c in df.columns if str(c) not in best_mapping]

        return SchemaMappingProposal(
            target_entity=best_entity,
            field_mappings=best_mapping,
            confidence_score=round(best_score, 2),
            status=status_str,
            missing_required_fields=best_missing,
            unmapped_columns=unmapped,
        )

    @classmethod
    def resolve_storage_path(cls, storage_key: str) -> Path:
        """
        Resolve filesystem path for a storage key.
        Checks the literal storage_key path, and if not found, checks relative to
        the configured settings.DATA_DIR.
        """
        p = Path(storage_key)
        if p.exists():
            return p
        base_dir = Path(getattr(settings, "DATA_DIR", "data"))
        normalized = storage_key.replace("\\", "/").lstrip("/")
        if normalized.startswith("data/"):
            rel_candidate = base_dir / normalized[len("data/"):]
            if rel_candidate.exists():
                return rel_candidate
        elif normalized.startswith("tenants/"):
            rel_candidate = base_dir / normalized
            if rel_candidate.exists():
                return rel_candidate
        fallback = base_dir / normalized
        if fallback.exists():
            return fallback
        return p

    @classmethod
    def get_dataset_preview(
        cls,
        db: Session,
        dataset_id: str,
        business_id: str,
        sample_size: int = 15,
    ) -> DataPreviewResponse:
        """Retrieve sanitized sample rows and metadata for customer preview."""
        dataset = db.execute(
            select(UploadedDataset).where(
                UploadedDataset.id == dataset_id,
                UploadedDataset.business_id == business_id,
            )
        ).scalar_one_or_none()

        if not dataset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset '{dataset_id}' not found.",
            )

        storage_path = cls.resolve_storage_path(dataset.storage_key)
        if not storage_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset file is no longer available on storage.",
            )

        try:
            if dataset.file_type == "csv":
                df = cls.read_csv_dataframe(storage_path, nrows=sample_size)
            else:
                df = pd.read_excel(storage_path, nrows=sample_size)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read dataset preview: {str(exc).splitlines()[0]}",
            )

        # Convert NaNs and dates to JSON-serializable primitives
        df_clean = df.replace({np.nan: None})
        sample_records: list[dict[str, Any]] = []
        for row in df_clean.to_dict(orient="records"):
            clean_row = {}
            for k, v in row.items():
                if isinstance(v, (datetime, date, pd.Timestamp)):
                    clean_row[k] = v.isoformat()
                elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    clean_row[k] = None
                else:
                    clean_row[k] = v
            sample_records.append(clean_row)

        schema_json = dataset.schema_json or {}
        col_profiles = schema_json.get("column_profiles", [])
        inferred_types = {cp["name"]: cp["data_type"] for cp in col_profiles}
        column_roles = {cp["name"]: cp["role"] for cp in col_profiles}
        mapping = schema_json.get("mapping_proposal", {})

        quality_report = dataset.quality_report_json or {}
        score = quality_report.get("readiness_score", 75)

        return DataPreviewResponse(
            dataset_id=dataset.id,
            filename=dataset.filename,
            row_count=dataset.row_count,
            total_rows=dataset.row_count,
            column_count=dataset.column_count,
            columns=list(df.columns),
            inferred_types=inferred_types,
            column_roles=column_roles,
            sample_rows=sample_records,
            readiness_status=dataset.readiness_status,
            readiness_score=score,
            detected_entity=mapping.get("target_entity"),
        )

    @classmethod
    def ingest_into_core_models(
        cls,
        db: Session,
        dataset_id: str,
        business_id: str,
        target_entity: str | None = None,
        column_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Commit mapped tabular records into unified NEXUS relational models idempotently.
        Manages durable IngestionJob lifecycle (PENDING -> PROCESSING -> COMPLETED | FAILED).
        Prevents duplicate row insertion on repeated ingestion.
        """
        dataset = db.execute(
            select(UploadedDataset).where(
                UploadedDataset.id == dataset_id,
                UploadedDataset.business_id == business_id,
            )
        ).scalar_one_or_none()

        if not dataset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset '{dataset_id}' not found.",
            )

        storage_path = cls.resolve_storage_path(dataset.storage_key)
        if not storage_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset storage file not found.",
            )

        schema_json = dataset.schema_json or {}
        mapping_info = schema_json.get("mapping_proposal", {})
        entity = target_entity or mapping_info.get("target_entity", "Sale")
        if entity.lower() in ("sale", "sales"):
            entity = "Sale"
        elif entity.lower() in ("product", "products"):
            entity = "Product"
        elif entity.lower() in ("customer", "customers"):
            entity = "Customer"
        elif entity.lower() in ("inventory", "inventories"):
            entity = "Inventory"
        elif entity.lower() in ("expense", "expenses"):
            entity = "Expense"
        elif entity.lower() in ("saleitem", "saleitems", "sale_item", "sale_items"):
            entity = "SaleItem"

        field_map = dict(mapping_info.get("field_mappings", {}))
        if column_overrides:
            field_map.update(column_overrides)

        dataset_version = schema_json.get("dataset_version", 1)

        # Idempotency Check: Was this dataset already ingested into this entity?
        completed_job = db.execute(
            select(IngestionJob).where(
                IngestionJob.business_id == business_id,
                IngestionJob.dataset_id == dataset_id,
                IngestionJob.target_entity == entity,
                IngestionJob.status == "COMPLETED",
            )
        ).scalars().first()
        if completed_job:
            logger.info(
                "Ingestion idempotent no-op: business_id=%s dataset_id=%s entity=%s job_id=%s",
                business_id, dataset_id, entity, completed_job.id,
            )
            # Reconcile pending scan if prior process crashed or failed before scan executed
            try:
                from app.analytics.continuous.service import ContinuousIntelligenceService
                ContinuousIntelligenceService.trigger_ingestion_scan(
                    db=db,
                    business_id=business_id,
                    organization_id=dataset.organization_id,
                    dataset_id=dataset.id,
                    ingestion_job_id=completed_job.id,
                    dataset_version=dataset_version,
                    entity=entity,
                )
            except Exception as rec_exc:  # noqa: BLE001
                logger.warning(
                    "Continuous intelligence scan reconciliation on retry encountered issue "
                    "for business %s (job %s): %s",
                    business_id,
                    completed_job.id,
                    rec_exc,
                )

            return {
                "dataset_id": dataset.id,
                "job_id": completed_job.id,
                "entity": entity,
                "target_entity": entity,
                "records_persisted": completed_job.rows_processed,
                "status": "COMPLETED",
                "message": f"Dataset already ingested into {entity} (idempotent no-op).",
            }

        # Check for existing PENDING or FAILED job for this dataset/entity to reuse (e.g. initial PENDING job created on upload)
        existing_job = db.execute(
            select(IngestionJob).where(
                IngestionJob.business_id == business_id,
                IngestionJob.dataset_id == dataset_id,
                IngestionJob.target_entity == entity,
                IngestionJob.status.in_(["PENDING", "FAILED"]),
            ).order_by(IngestionJob.created_at.desc())
        ).scalars().first()

        if existing_job:
            job = existing_job
            job.status = "PROCESSING"
            job.started_at = datetime.now(UTC)
            job.completed_at = None
            job.error_message = None
        else:
            job = IngestionJob(
                id=str(uuid4()),
                organization_id=dataset.organization_id,
                business_id=business_id,
                dataset_id=dataset_id,
                status="PROCESSING",
                target_entity=entity,
                started_at=datetime.now(UTC),
            )
            db.add(job)
        db.commit()
        job_id = job.id
        logger.info(
            "Ingestion job started: business_id=%s dataset_id=%s entity=%s job_id=%s",
            business_id, dataset_id, entity, job_id,
        )

        try:
            # 1. Load DataFrame with deliberate multi-encoding fallback
            if dataset.file_type == "csv":
                df = cls.read_csv_dataframe(storage_path)
            else:
                try:
                    df = pd.read_excel(storage_path)
                except Exception as exc:  # noqa: BLE001
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Failed to read stored Excel workbook: {str(exc).splitlines()[0]}",
                    )

            df = df.replace({np.nan: None})
            row_errors: list[dict[str, Any]] = []
            staged_objects: list[Any] = []
            records_inserted = 0

            # 2. Check Entity-Specific Required Columns & Ingest Logic
            if entity == "Sale":
                amount_col = next((c for c, f in field_map.items() if f == "amount"), None)
                date_col = next((c for c, f in field_map.items() if f == "date"), None)
                order_col = next((c for c, f in field_map.items() if f == "order_number"), None)

                if not amount_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest Sales: missing required 'amount' column mapping.",
                    )

                # Ensure a valid default customer exists for this business
                cust = db.execute(
                    select(Customer).where(Customer.business_id == business_id)
                ).scalars().first()
                if not cust:
                    cust_hex = uuid4().hex[:8]
                    cust = Customer(
                        business_id=business_id,
                        customer_code=f"CUST-{cust_hex.upper()}",
                        name="Default Customer",
                        email=f"customer-{cust_hex}@nexus.local",
                        city="Default City",
                        customer_segment="Retail",
                        acquisition_date=datetime.now(tz=UTC).date(),
                    )
                    db.add(cust)
                    db.flush()

                # Pre-fetch existing order numbers for this business in batches
                order_vals = [
                    str(r[order_col]).strip()
                    for _, r in df.iterrows()
                    if order_col and r[order_col] is not None and str(r[order_col]).strip()
                ]
                existing_orders_set: set[str] = set()
                if order_vals:
                    for i in range(0, len(order_vals), 1000):
                        batch = order_vals[i : i + 1000]
                        found = db.execute(
                            select(Sale.transaction_number).where(
                                Sale.business_id == business_id,
                                Sale.transaction_number.in_(batch),
                            )
                        ).scalars().all()
                        existing_orders_set.update(found)

                # Multi-line order aggregation map (preserves all line items for an order)
                staged_sales_by_order: dict[str, Sale] = {}

                for idx, row in df.iterrows():
                    row_num = idx + 1
                    val = row[amount_col]
                    if val is None or str(val).strip() == "":
                        row_errors.append({
                            "row": row_num,
                            "column": amount_col,
                            "value": None,
                            "error_type": "REQUIRED_VALUE_MISSING",
                            "message": "Sale amount cannot be null or empty.",
                        })
                        continue

                    try:
                        clean_val = str(val).replace("$", "").replace(",", "").strip()
                        num_amount = round(Decimal(clean_val), 2)
                    except (InvalidOperation, ValueError, TypeError):
                        row_errors.append({
                            "row": row_num,
                            "column": amount_col,
                            "value": str(val)[:50],
                            "error_type": "INVALID_NUMERIC",
                            "message": f"Invalid numerical sale amount '{val}'.",
                        })
                        continue

                    sale_dt = datetime.now(UTC)
                    if date_col and row[date_col] is not None and str(row[date_col]).strip() != "":
                        try:
                            sale_dt = pd.to_datetime(row[date_col]).to_pydatetime()
                            if sale_dt.tzinfo is None:
                                sale_dt = sale_dt.replace(tzinfo=UTC)
                        except Exception:  # noqa: BLE001
                            row_errors.append({
                                "row": row_num,
                                "column": date_col,
                                "value": str(row[date_col])[:50],
                                "error_type": "UNPARSEABLE_DATE",
                                "message": f"Invalid or unparseable transaction date '{row[date_col]}'.",
                            })
                            continue

                    sale_order = (
                        str(row[order_col]).strip()
                        if order_col and row[order_col] is not None and str(row[order_col]).strip()
                        else f"TXN-{uuid4().hex[:8]}"
                    )

                    # Multi-line order preservation: If order is already staged in this batch,
                    # aggregate line items into the overarching Sale order total rather than dropping them
                    if sale_order in staged_sales_by_order:
                        existing_sale = staged_sales_by_order[sale_order]
                        existing_sale.subtotal += num_amount
                        existing_sale.total_amount += num_amount
                        continue

                    # Deduplication guard: Skip if already committed in DB from previous ingestion
                    if sale_order in existing_orders_set:
                        continue

                    sale = Sale(
                        business_id=business_id,
                        transaction_number=sale_order,
                        customer_id=cust.id,
                        transaction_date=sale_dt,
                        subtotal=num_amount,
                        discount_amount=Decimal("0.00"),
                        tax_amount=Decimal("0.00"),
                        total_amount=num_amount,
                        status="completed",
                    )
                    staged_sales_by_order[sale_order] = sale
                    staged_objects.append(sale)

            elif entity == "Product":
                sku_col = next((c for c, f in field_map.items() if f == "sku"), None)
                name_col = next((c for c, f in field_map.items() if f == "name"), None)
                price_col = next((c for c, f in field_map.items() if f == "selling_price"), None)
                cost_col = next((c for c, f in field_map.items() if f == "unit_cost"), None)
                cat_col = next((c for c, f in field_map.items() if f == "category"), None)
                subcat_col = next((c for c, f in field_map.items() if f == "subcategory"), None)

                if not sku_col or not name_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest Products: missing 'sku' or 'name' mapping.",
                    )

                sku_vals = [
                    str(r[sku_col]).strip()
                    for _, r in df.iterrows()
                    if r[sku_col] is not None and str(r[sku_col]).strip()
                ]
                existing_skus_set: set[str] = set()
                if sku_vals:
                    for i in range(0, len(sku_vals), 1000):
                        batch = sku_vals[i : i + 1000]
                        found = db.execute(
                            select(Product.sku).where(
                                Product.business_id == business_id,
                                Product.sku.in_(batch),
                            )
                        ).scalars().all()
                        existing_skus_set.update(found)

                seen_skus_in_file: set[str] = set()

                for idx, row in df.iterrows():
                    row_num = idx + 1
                    raw_sku = row[sku_col]
                    if raw_sku is None or str(raw_sku).strip() == "":
                        row_errors.append({
                            "row": row_num,
                            "column": sku_col,
                            "value": None,
                            "error_type": "REQUIRED_VALUE_MISSING",
                            "message": "Product SKU cannot be null or empty.",
                        })
                        continue

                    sku_val = str(raw_sku).strip()

                    raw_name = row[name_col]
                    if raw_name is None or str(raw_name).strip() == "":
                        row_errors.append({
                            "row": row_num,
                            "column": name_col,
                            "value": None,
                            "error_type": "REQUIRED_VALUE_MISSING",
                            "message": "Product name cannot be null or empty.",
                        })
                        continue

                    name_val = str(raw_name).strip()

                    price_val = Decimal("0.00")
                    if price_col and row[price_col] is not None and str(row[price_col]).strip() != "":
                        try:
                            clean_price = str(row[price_col]).replace("$", "").replace(",", "").strip()
                            price_val = round(Decimal(clean_price), 2)
                            if price_val < 0:
                                row_errors.append({
                                    "row": row_num,
                                    "column": price_col,
                                    "value": str(row[price_col]),
                                    "error_type": "RANGE_ERROR",
                                    "message": "Product selling price cannot be negative.",
                                })
                                continue
                        except Exception:  # noqa: BLE001
                            row_errors.append({
                                "row": row_num,
                                "column": price_col,
                                "value": str(row[price_col])[:50],
                                "error_type": "INVALID_NUMERIC",
                                "message": f"Invalid numerical selling price '{row[price_col]}'.",
                            })
                            continue

                    cost_val = Decimal("0.00")
                    if cost_col and row[cost_col] is not None and str(row[cost_col]).strip() != "":
                        try:
                            clean_cost = str(row[cost_col]).replace("$", "").replace(",", "").strip()
                            cost_val = round(Decimal(clean_cost), 2)
                            if cost_val < 0:
                                row_errors.append({
                                    "row": row_num,
                                    "column": cost_col,
                                    "value": str(row[cost_col]),
                                    "error_type": "RANGE_ERROR",
                                    "message": "Product unit cost cannot be negative.",
                                })
                                continue
                        except Exception:  # noqa: BLE001
                            row_errors.append({
                                "row": row_num,
                                "column": cost_col,
                                "value": str(row[cost_col])[:50],
                                "error_type": "INVALID_NUMERIC",
                                "message": f"Invalid numerical unit cost '{row[cost_col]}'.",
                            })
                            continue

                    cat_val = str(row[cat_col]).strip() if cat_col and row[cat_col] is not None else "General"
                    subcat_val = str(row[subcat_col]).strip() if subcat_col and row[subcat_col] is not None else cat_val

                    if sku_val in seen_skus_in_file:
                        continue
                    seen_skus_in_file.add(sku_val)

                    if sku_val in existing_skus_set:
                        continue
                    existing_skus_set.add(sku_val)

                    prod = Product(
                        business_id=business_id,
                        sku=sku_val,
                        name=name_val,
                        selling_price=price_val,
                        unit_cost=cost_val,
                        category=cat_val,
                        subcategory=subcat_val,
                        active=True,
                    )
                    staged_objects.append(prod)

            elif entity == "Customer":
                code_col = next((c for c, f in field_map.items() if f == "customer_code"), None)
                name_col = next((c for c, f in field_map.items() if f == "name"), None)
                email_col = next((c for c, f in field_map.items() if f == "email"), None)
                city_col = next((c for c, f in field_map.items() if f == "city"), None)
                segment_col = next((c for c, f in field_map.items() if f == "customer_segment"), None)
                acq_col = next((c for c, f in field_map.items() if f == "acquisition_date"), None)

                if not name_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest Customers: missing 'name' mapping.",
                    )

                # Pre-fetch existing customer codes and emails SCOPED STRICTLY TO BUSINESS_ID
                existing_codes_set: set[str] = set()
                existing_emails_set: set[str] = set()
                existing_custs = db.execute(
                    select(Customer.customer_code, Customer.email).where(
                        Customer.business_id == business_id
                    )
                ).all()
                for c_code, c_email in existing_custs:
                    if c_code:
                        existing_codes_set.add(c_code)
                    if c_email:
                        existing_emails_set.add(c_email.lower())

                seen_codes_in_file: set[str] = set()
                seen_emails_in_file: set[str] = set()

                for idx, row in df.iterrows():
                    row_num = idx + 1
                    raw_name = row[name_col]
                    if raw_name is None or str(raw_name).strip() == "":
                        row_errors.append({
                            "row": row_num,
                            "column": name_col,
                            "value": None,
                            "error_type": "REQUIRED_VALUE_MISSING",
                            "message": "Customer name cannot be null or empty.",
                        })
                        continue

                    cust_name = str(raw_name).strip()
                    cust_code = (
                        str(row[code_col]).strip()
                        if code_col and row[code_col] is not None and str(row[code_col]).strip()
                        else f"CUST-{uuid4().hex[:6].upper()}"
                    )
                    cust_email = (
                        str(row[email_col]).strip().lower()
                        if email_col and row[email_col] is not None and str(row[email_col]).strip()
                        else f"cust-{uuid4().hex[:8]}@nexus.local"
                    )
                    cust_city = str(row[city_col]).strip() if city_col and row[city_col] is not None else "Unknown"
                    cust_seg = str(row[segment_col]).strip() if segment_col and row[segment_col] is not None else "Retail"

                    acq_dt = datetime.now(tz=UTC).date()
                    if acq_col and row[acq_col] is not None and str(row[acq_col]).strip() != "":
                        try:
                            acq_dt = pd.to_datetime(row[acq_col]).date()
                        except Exception:  # noqa: BLE001
                            row_errors.append({
                                "row": row_num,
                                "column": acq_col,
                                "value": str(row[acq_col])[:50],
                                "error_type": "UNPARSEABLE_DATE",
                                "message": f"Invalid customer acquisition date '{row[acq_col]}'.",
                            })
                            continue

                    if cust_code in seen_codes_in_file or cust_email in seen_emails_in_file:
                        continue
                    seen_codes_in_file.add(cust_code)
                    seen_emails_in_file.add(cust_email)

                    if cust_code in existing_codes_set or cust_email in existing_emails_set:
                        continue
                    existing_codes_set.add(cust_code)
                    existing_emails_set.add(cust_email)

                    cust = Customer(
                        business_id=business_id,
                        customer_code=cust_code,
                        name=cust_name,
                        email=cust_email,
                        city=cust_city,
                        customer_segment=cust_seg,
                        acquisition_date=acq_dt,
                    )
                    staged_objects.append(cust)

            elif entity == "Inventory":
                prod_col = next((c for c, f in field_map.items() if f in ("product_id", "sku")), None)
                stock_col = next((c for c, f in field_map.items() if f == "stock_quantity"), None)
                threshold_col = next((c for c, f in field_map.items() if f == "reorder_threshold"), None)
                wh_col = next((c for c, f in field_map.items() if f in ("warehouse", "warehouse_location")), None)

                if not prod_col or not stock_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest Inventory: missing required 'product_id' or 'stock_quantity' mapping.",
                    )

                # Pre-fetch products for this business
                biz_prods = db.execute(
                    select(Product.id, Product.sku).where(Product.business_id == business_id)
                ).all()
                sku_to_id = {sku: pid for pid, sku in biz_prods}
                valid_prod_ids = {pid for pid, _ in biz_prods}

                # Pre-fetch existing inventory records for this business
                existing_invs = db.execute(
                    select(Inventory).where(Inventory.business_id == business_id)
                ).scalars().all()
                existing_inv_map = {inv.product_id: inv for inv in existing_invs}

                seen_inv_prods: set[int] = set()

                for idx, row in df.iterrows():
                    row_num = idx + 1
                    raw_prod = row[prod_col]
                    if raw_prod is None or str(raw_prod).strip() == "":
                        row_errors.append({
                            "row": row_num,
                            "column": prod_col,
                            "value": None,
                            "error_type": "REQUIRED_VALUE_MISSING",
                            "message": "Product reference cannot be null or empty.",
                        })
                        continue

                    prod_str = str(raw_prod).strip()
                    matched_pid = None
                    if prod_str in sku_to_id:
                        matched_pid = sku_to_id[prod_str]
                    elif prod_str.isdigit() and int(prod_str) in valid_prod_ids:
                        matched_pid = int(prod_str)

                    if matched_pid is None:
                        row_errors.append({
                            "row": row_num,
                            "column": prod_col,
                            "value": prod_str[:50],
                            "error_type": "FOREIGN_KEY_NOT_FOUND",
                            "message": f"Product '{prod_str}' does not exist in catalog for this business.",
                        })
                        continue

                    raw_stock = row[stock_col]
                    if raw_stock is None or str(raw_stock).strip() == "":
                        row_errors.append({
                            "row": row_num,
                            "column": stock_col,
                            "value": None,
                            "error_type": "REQUIRED_VALUE_MISSING",
                            "message": "Stock quantity cannot be null or empty.",
                        })
                        continue

                    try:
                        clean_stock = str(raw_stock).replace(",", "").strip()
                        stock_qty = int(float(clean_stock))
                        if stock_qty < 0:
                            row_errors.append({
                                "row": row_num,
                                "column": stock_col,
                                "value": str(raw_stock),
                                "error_type": "RANGE_ERROR",
                                "message": "Stock quantity cannot be negative.",
                            })
                            continue
                    except Exception:  # noqa: BLE001
                        row_errors.append({
                            "row": row_num,
                            "column": stock_col,
                            "value": str(raw_stock)[:50],
                            "error_type": "INVALID_NUMERIC",
                            "message": f"Invalid numerical stock quantity '{raw_stock}'.",
                        })
                        continue

                    thresh_val = 10
                    if threshold_col and row[threshold_col] is not None and str(row[threshold_col]).strip() != "":
                        try:
                            thresh_val = int(float(str(row[threshold_col]).replace(",", "").strip()))
                            if thresh_val < 0:
                                row_errors.append({
                                    "row": row_num,
                                    "column": threshold_col,
                                    "value": str(row[threshold_col]),
                                    "error_type": "RANGE_ERROR",
                                    "message": "Reorder threshold cannot be negative.",
                                })
                                continue
                        except Exception:  # noqa: BLE001
                            row_errors.append({
                                "row": row_num,
                                "column": threshold_col,
                                "value": str(row[threshold_col])[:50],
                                "error_type": "INVALID_NUMERIC",
                                "message": f"Invalid numerical reorder threshold '{row[threshold_col]}'.",
                            })
                            continue

                    wh_val = str(row[wh_col]).strip() if wh_col and row[wh_col] is not None else "Main Warehouse"

                    if matched_pid in seen_inv_prods:
                        continue
                    seen_inv_prods.add(matched_pid)

                    if matched_pid in existing_inv_map:
                        existing_inv = existing_inv_map[matched_pid]
                        existing_inv.stock_quantity = stock_qty
                        existing_inv.reorder_threshold = thresh_val
                        existing_inv.warehouse_location = wh_val
                    else:
                        inv = Inventory(
                            business_id=business_id,
                            product_id=matched_pid,
                            stock_quantity=stock_qty,
                            reorder_threshold=thresh_val,
                            warehouse_location=wh_val,
                        )
                        staged_objects.append(inv)

            elif entity == "Expense":
                date_col = next((c for c, f in field_map.items() if f == "expense_date"), None)
                cat_col = next((c for c, f in field_map.items() if f == "category"), None)
                amount_col = next((c for c, f in field_map.items() if f == "amount"), None)
                desc_col = next((c for c, f in field_map.items() if f in ("description", "vendor")), None)

                if not cat_col or not amount_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest Expenses: missing required 'category' or 'amount' column mapping.",
                    )

                seen_expenses_in_file: set[tuple] = set()

                for idx, row in df.iterrows():
                    row_num = idx + 1
                    raw_cat = row[cat_col]
                    if raw_cat is None or str(raw_cat).strip() == "":
                        row_errors.append({
                            "row": row_num,
                            "column": cat_col,
                            "value": None,
                            "error_type": "REQUIRED_VALUE_MISSING",
                            "message": "Expense category cannot be null or empty.",
                        })
                        continue

                    cat = str(raw_cat).strip()

                    raw_amt = row[amount_col]
                    if raw_amt is None or str(raw_amt).strip() == "":
                        row_errors.append({
                            "row": row_num,
                            "column": amount_col,
                            "value": None,
                            "error_type": "REQUIRED_VALUE_MISSING",
                            "message": "Expense amount cannot be null or empty.",
                        })
                        continue

                    try:
                        clean_amt = str(raw_amt).replace("$", "").replace(",", "").strip()
                        amt = round(Decimal(clean_amt), 2)
                        if amt < 0:
                            row_errors.append({
                                "row": row_num,
                                "column": amount_col,
                                "value": str(raw_amt),
                                "error_type": "RANGE_ERROR",
                                "message": "Expense amount cannot be negative.",
                            })
                            continue
                    except Exception:  # noqa: BLE001
                        row_errors.append({
                            "row": row_num,
                            "column": amount_col,
                            "value": str(raw_amt)[:50],
                            "error_type": "INVALID_NUMERIC",
                            "message": f"Invalid numerical expense amount '{raw_amt}'.",
                        })
                        continue

                    exp_dt = datetime.now(tz=UTC).date()
                    if date_col and row[date_col] is not None and str(row[date_col]).strip() != "":
                        try:
                            exp_dt = pd.to_datetime(row[date_col]).date()
                        except Exception:  # noqa: BLE001
                            row_errors.append({
                                "row": row_num,
                                "column": date_col,
                                "value": str(row[date_col])[:50],
                                "error_type": "UNPARSEABLE_DATE",
                                "message": f"Invalid expense date '{row[date_col]}'.",
                            })
                            continue

                    desc = str(row[desc_col]).strip() if desc_col and row[desc_col] is not None else "Business Expense"

                    exp_key = (exp_dt, cat, amt, desc)
                    if exp_key in seen_expenses_in_file:
                        continue
                    seen_expenses_in_file.add(exp_key)

                    # Deduplication guard against existing expenses
                    existing_exp = db.execute(
                        select(Expense.id).where(
                            Expense.business_id == business_id,
                            Expense.expense_date == exp_dt,
                            Expense.category == cat,
                            Expense.amount == amt,
                            Expense.description == desc,
                        )
                    ).scalars().first()
                    if existing_exp:
                        continue

                    exp = Expense(
                        business_id=business_id,
                        expense_date=exp_dt,
                        category=cat,
                        amount=amt,
                        description=desc,
                    )
                    staged_objects.append(exp)

            elif entity == "SaleItem":
                sale_ref_col = (
                    next((c for c, f in field_map.items() if f in ("sale_id", "sale_ref", "transaction_number", "order_number")), None)
                    or next((c for c in df.columns if str(c).lower().strip() in ("transaction_number", "order_number", "sale_id", "sale_ref", "transaction_id", "order_id", "invoice_id")), None)
                )
                prod_ref_col = (
                    next((c for c, f in field_map.items() if f in ("product_id", "product_ref", "sku", "product_sku")), None)
                    or next((c for c in df.columns if str(c).lower().strip() in ("sku", "product_sku", "product_id", "product_ref", "item_id", "item_code")), None)
                )
                qty_col = (
                    next((c for c, f in field_map.items() if f in ("quantity", "qty", "units")), None)
                    or next((c for c in df.columns if str(c).lower().strip() in ("quantity", "qty", "units", "count")), None)
                )
                price_col = (
                    next((c for c, f in field_map.items() if f in ("unit_price", "price", "rate")), None)
                    or next((c for c in df.columns if str(c).lower().strip() in ("unit_price", "price", "rate", "item_price")), None)
                )
                discount_col = (
                    next((c for c, f in field_map.items() if f in ("discount_amount", "discount", "promo")), None)
                    or next((c for c in df.columns if str(c).lower().strip() in ("discount_amount", "discount", "promo")), None)
                )
                line_total_col = (
                    next((c for c, f in field_map.items() if f in ("line_total", "total", "subtotal", "line_amount")), None)
                    or next((c for c in df.columns if str(c).lower().strip() in ("line_total", "total", "subtotal", "line_amount")), None)
                )

                if not sale_ref_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest SaleItems: missing required sale reference ('sale_id', 'transaction_number', or 'order_number') column mapping.",
                    )

                if not prod_ref_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest SaleItems: missing required product reference ('sku' or 'product_id') column mapping.",
                    )

                if not qty_col or not price_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest SaleItems: missing required 'quantity' or 'unit_price' column.",
                    )

                # Tenant-safe parent lookup pre-fetch:
                # Resolve sale transaction_number -> sale.id (scoped strictly to business_id)
                sales_rows = db.execute(
                    select(Sale.id, Sale.transaction_number).where(Sale.business_id == business_id)
                ).all()
                txn_to_sale_id: dict[str, int] = {
                    str(s.transaction_number).strip(): s.id for s in sales_rows
                }

                # Resolve product sku -> product.id (scoped strictly to business_id)
                prod_rows = db.execute(
                    select(Product.id, Product.sku).where(Product.business_id == business_id)
                ).all()
                sku_to_prod_id: dict[str, int] = {
                    str(p.sku).strip(): p.id for p in prod_rows
                }

                # Deduplication map of existing sale_items in database for this business
                existing_items_rows = db.execute(
                    select(SaleItem.sale_id, SaleItem.product_id).join(
                        Sale, SaleItem.sale_id == Sale.id
                    ).where(Sale.business_id == business_id)
                ).all()
                existing_items_set: set[tuple[int, int]] = {
                    (row.sale_id, row.product_id) for row in existing_items_rows
                }
                seen_items_in_batch: set[tuple[int, int]] = set()

                for idx, row in df.iterrows():
                    row_num = idx + 1

                    # 1. Resolve Parent Sale by natural key
                    raw_sale_ref = str(row[sale_ref_col]).strip() if row[sale_ref_col] is not None else ""
                    if not raw_sale_ref:
                        row_errors.append({
                            "row": row_num,
                            "column": sale_ref_col,
                            "value": None,
                            "error_type": "REQUIRED_VALUE_MISSING",
                            "message": "Sale transaction reference cannot be empty.",
                        })
                        continue

                    matched_sale_id = txn_to_sale_id.get(raw_sale_ref)
                    if matched_sale_id is None:
                        row_errors.append({
                            "row": row_num,
                            "column": sale_ref_col,
                            "value": raw_sale_ref[:50],
                            "error_type": "UNRESOLVED_REFERENCE",
                            "message": f"Sale transaction reference '{raw_sale_ref}' could not be resolved to any existing sale in this business.",
                        })
                        continue

                    # 2. Resolve Product by SKU
                    raw_prod_ref = str(row[prod_ref_col]).strip() if row[prod_ref_col] is not None else ""
                    if not raw_prod_ref:
                        row_errors.append({
                            "row": row_num,
                            "column": prod_ref_col,
                            "value": None,
                            "error_type": "REQUIRED_VALUE_MISSING",
                            "message": "Product SKU reference cannot be empty.",
                        })
                        continue

                    matched_prod_id = sku_to_prod_id.get(raw_prod_ref)
                    if matched_prod_id is None:
                        row_errors.append({
                            "row": row_num,
                            "column": prod_ref_col,
                            "value": raw_prod_ref[:50],
                            "error_type": "UNRESOLVED_REFERENCE",
                            "message": f"Product SKU reference '{raw_prod_ref}' could not be resolved to any existing product in this business.",
                        })
                        continue

                    # 3. Quantity validation
                    try:
                        qty = int(row[qty_col]) if qty_col and row[qty_col] is not None else 1
                        if qty <= 0:
                            row_errors.append({
                                "row": row_num,
                                "column": qty_col,
                                "value": str(row[qty_col]),
                                "error_type": "RANGE_ERROR",
                                "message": "SaleItem quantity must be strictly greater than 0.",
                            })
                            continue
                    except Exception:  # noqa: BLE001
                        row_errors.append({
                            "row": row_num,
                            "column": qty_col,
                            "value": str(row[qty_col])[:50],
                            "error_type": "INVALID_NUMERIC",
                            "message": f"Invalid integer quantity '{row[qty_col]}'.",
                        })
                        continue

                    # 4. Unit Price validation
                    try:
                        u_price = (
                            Decimal(str(round(float(str(row[price_col]).replace("$", "").replace(",", "")), 2)))
                            if price_col and row[price_col] is not None
                            else Decimal("0.00")
                        )
                        if u_price < 0:
                            row_errors.append({
                                "row": row_num,
                                "column": price_col,
                                "value": str(row[price_col]),
                                "error_type": "RANGE_ERROR",
                                "message": "SaleItem unit price cannot be negative.",
                            })
                            continue
                    except Exception:  # noqa: BLE001
                        row_errors.append({
                            "row": row_num,
                            "column": price_col,
                            "value": str(row[price_col])[:50],
                            "error_type": "INVALID_NUMERIC",
                            "message": f"Invalid unit price '{row[price_col]}'.",
                        })
                        continue

                    # 5. Discount Amount (optional)
                    disc_val = Decimal("0.00")
                    if discount_col and row[discount_col] is not None and str(row[discount_col]).strip() != "":
                        try:
                            clean_disc = str(row[discount_col]).replace("$", "").replace(",", "").strip()
                            disc_val = max(Decimal("0.00"), round(Decimal(clean_disc), 2))
                        except Exception:  # noqa: BLE001
                            row_errors.append({
                                "row": row_num,
                                "column": discount_col,
                                "value": str(row[discount_col])[:50],
                                "error_type": "INVALID_NUMERIC",
                                "message": f"Invalid numerical discount amount '{row[discount_col]}'.",
                            })
                            continue

                    # 6. Line Total calculation
                    l_total = max(Decimal("0.00"), (u_price * qty) - disc_val)
                    if line_total_col and row[line_total_col] is not None and str(row[line_total_col]).strip() != "":
                        try:
                            clean_lt = str(row[line_total_col]).replace("$", "").replace(",", "").strip()
                            l_total = max(Decimal("0.00"), round(Decimal(clean_lt), 2))
                        except Exception:  # noqa: BLE001
                            pass

                    # 7. Idempotency deduplication check
                    item_key = (matched_sale_id, matched_prod_id)
                    if item_key in seen_items_in_batch or item_key in existing_items_set:
                        continue
                    seen_items_in_batch.add(item_key)

                    s_item = SaleItem(
                        sale_id=matched_sale_id,
                        product_id=matched_prod_id,
                        quantity=qty,
                        unit_price=u_price,
                        discount_amount=disc_val,
                        line_total=l_total,
                    )
                    staged_objects.append(s_item)

            # 3. Check for Row Validation Errors - Rollback if any found
            if row_errors:
                db.rollback()
                failed_job = db.execute(select(IngestionJob).where(IngestionJob.id == job_id)).scalar_one_or_none()
                if failed_job:
                    failed_job.status = "FAILED"
                    failed_job.completed_at = datetime.now(UTC)
                    first_err = row_errors[0]
                    failed_job.error_message = (
                        f"Validation failed on {len(row_errors)} row(s). Row {first_err['row']} [{first_err['column']}]: {first_err['message']}"
                    )[:500]

                dataset_ref = db.execute(select(UploadedDataset).where(UploadedDataset.id == dataset_id)).scalar_one_or_none()
                sanitized_errors = []
                for err in row_errors[:50]:
                    sanitized_errors.append({
                        "row": int(err.get("row", 0)),
                        "column": str(err.get("column", ""))[:100],
                        "value": str(err.get("value", ""))[:100] if err.get("value") is not None else None,
                        "error_type": str(err.get("error_type", "VALIDATION_ERROR"))[:50],
                        "message": str(err.get("message", ""))[:250],
                    })
                if dataset_ref:
                    s_copy = dict(dataset_ref.schema_json or {})
                    s_copy["ingestion_status"] = "FAILED"
                    s_copy["ingestion_errors"] = sanitized_errors
                    s_copy["total_validation_errors"] = len(row_errors)
                    dataset_ref.schema_json = s_copy
                    dataset_ref.readiness_status = "REQUIRES_REVIEW"
                    flag_modified(dataset_ref, "schema_json")

                db.commit()
                logger.warning(
                    "Ingestion rejected with row validation errors: business_id=%s dataset_id=%s errors=%d",
                    business_id, dataset_id, len(row_errors),
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": f"Ingestion rejected: {len(row_errors)} validation error(s) detected.",
                        "total_errors": len(row_errors),
                        "errors": sanitized_errors,
                    },
                )

            # 4. Commit Validated Records
            for obj in staged_objects:
                db.add(obj)

            records_inserted = len(staged_objects)

            # Update IngestionJob to COMPLETED
            running_job = db.execute(select(IngestionJob).where(IngestionJob.id == job_id)).scalar_one_or_none()
            if running_job:
                running_job.status = "COMPLETED"
                running_job.completed_at = datetime.now(UTC)
                running_job.rows_processed = records_inserted

            # Update dataset metadata with new dict copy and flag_modified
            schema_copy = dict(dataset.schema_json or {})
            schema_copy["ingestion_status"] = "COMPLETED"
            schema_copy.pop("ingestion_errors", None)
            schema_copy["total_validation_errors"] = 0
            schema_copy["ingested_at"] = datetime.now(UTC).isoformat()
            schema_copy["records_persisted"] = records_inserted
            schema_copy["dataset_version"] = dataset_version
            schema_copy["source_filename"] = dataset.filename
            schema_copy["content_hash"] = dataset.content_hash
            schema_copy["ingestion_job_id"] = job_id
            if "mapping_proposal" in schema_copy:
                prop_copy = dict(schema_copy["mapping_proposal"])
                prop_copy["status"] = "MAPPED"
                prop_copy["field_mappings"] = field_map
                prop_copy["missing_required_fields"] = []
                prop_copy["target_entity"] = entity
                schema_copy["mapping_proposal"] = prop_copy
            dataset.schema_json = schema_copy
            dataset.readiness_status = "READY"
            flag_modified(dataset, "schema_json")

            # Update business data readiness status
            biz = db.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
            if biz:
                biz.data_readiness_status = "READY"
                biz.onboarding_step = "completed"

            db.commit()
            db.refresh(dataset)
            logger.info(
                "Ingestion job COMPLETED: business_id=%s dataset_id=%s entity=%s job_id=%s records=%d",
                business_id, dataset_id, entity, job_id, records_inserted,
            )

            # Phase 17: Automatic Business Understanding and Semantic Activation upon DATASET READY
            try:
                from app.services.tenant_semantic_service import TenantSemanticService
                TenantSemanticService.generate_business_understanding(
                    business_id=business_id,
                    organization_id=dataset.organization_id,
                    db=db,
                    source_dataset_id=dataset.id,
                )
            except Exception as sem_exc:  # noqa: BLE001
                db.rollback()
                logger.warning(
                    "Automatic semantic activation encountered an issue for business %s: %s",
                    business_id,
                    sem_exc,
                )

            # Phase 29 Stage 2: Automatic Continuous Intelligence Scan upon Ingestion Completion
            scan_run_id = None
            try:
                from app.analytics.continuous.service import ContinuousIntelligenceService
                scan_res = ContinuousIntelligenceService.trigger_ingestion_scan(
                    db=db,
                    business_id=business_id,
                    organization_id=dataset.organization_id,
                    dataset_id=dataset.id,
                    ingestion_job_id=job_id,
                    dataset_version=dataset_version,
                    entity=entity,
                )
                if scan_res:
                    scan_run_id = scan_res.scan_run_id
            except Exception as scan_exc:  # noqa: BLE001
                db.rollback()
                logger.warning(
                    "Continuous intelligence ingestion-triggered scan encountered an issue for business %s (job %s): %s",
                    business_id,
                    job_id,
                    scan_exc,
                )

            res_dict = {
                "dataset_id": dataset.id,
                "job_id": job_id,
                "entity": entity,
                "target_entity": entity,
                "records_persisted": records_inserted,
                "status": "COMPLETED",
                "message": f"Successfully ingested {records_inserted} records into {entity} domain.",
            }
            if scan_run_id is not None:
                res_dict["scan_run_id"] = scan_run_id
            return res_dict

        except HTTPException:
            db.rollback()
            failed_job = db.execute(select(IngestionJob).where(IngestionJob.id == job_id)).scalar_one_or_none()
            if failed_job and failed_job.status != "FAILED":
                failed_job.status = "FAILED"
                failed_job.completed_at = datetime.now(UTC)
                failed_job.error_message = "Ingestion rejected due to schema or constraint validation."
                db.commit()
            raise
        except Exception as exc:
            db.rollback()
            safe_msg = f"Ingestion failed: {str(exc).splitlines()[0]}"
            failed_job = db.execute(select(IngestionJob).where(IngestionJob.id == job_id)).scalar_one_or_none()
            if failed_job:
                failed_job.status = "FAILED"
                failed_job.completed_at = datetime.now(UTC)
                failed_job.error_message = safe_msg[:500]
                db.commit()
            logger.error(
                "Ingestion job FAILED (exception): business_id=%s dataset_id=%s entity=%s job_id=%s error=%s",
                business_id, dataset_id, entity, job_id, safe_msg,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=safe_msg,
            ) from exc
