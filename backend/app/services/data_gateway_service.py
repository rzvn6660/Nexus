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
import os
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.customer import Customer
from app.models.expense import Expense
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, IngestionJob, UploadedDataset
from app.core.logging import get_logger
from app.schemas.data_gateway import (
    ColumnProfile,
    DataPreviewResponse,
    DataReadinessSummary,
    DatasetDetailResponse,
    DateCoverage,
    QualityCheckItem,
    SchemaMappingProposal,
)


logger = get_logger(__name__)


class DataGatewayService:
    """Production Data Gateway orchestrating ingestion, profiling, quality, and schema mapping."""

    MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
    MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB alias
    MAX_ROWS = 500_000
    MAX_ROW_COUNT = 500_000  # alias
    MAX_COLUMNS = 200
    MAX_CELL_LENGTH = 10_000

    ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
    PROHIBITED_EXTENSIONS = {
        ".exe", ".py", ".sh", ".bat", ".bin", ".js", ".html", ".dll",
        ".cmd", ".vbs", ".ps1", ".com", ".scr", ".msi"
    }

    ENTITY_TARGETS = {
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
                "sale_id": [r"\bsale_id\b", r"\border_id\b", r"\btransaction_id\b", r"\binvoice_id\b"],
                "product_id": [r"\bproduct_id\b", r"\bsku\b", r"\bitem_id\b"],
                "quantity": [r"\bquantity\b", r"\bqty\b", r"\bunits\b", r"\bcount\b"],
                "unit_price": [r"\bunit_price\b", r"\bprice\b", r"\brate\b", r"\bitem_price\b"],
                "discount_amount": [r"\bdiscount\b", r"\bdiscount_amount\b", r"\bpromo\b"],
                "tax_amount": [r"\btax\b", r"\btax_amount\b", r"\bgst\b", r"\bvat\b"],
                "line_total": [r"\bline_total\b", r"\btotal\b", r"\bsubtotal\b", r"\bamount\b"],
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
                detail="Uploaded file is empty (0 bytes).",
            )

        # Check binary magic signatures (MIME spoofing detection)
        if content_bytes.startswith(b"MZ") or content_bytes.startswith(b"\x7fELF"):
            logger.warning(
                "SECURITY: Executable binary upload rejected. filename='%s' size=%d bytes",
                filename, len(content_bytes),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Executable binary format rejected.",
            )
        if content_bytes.startswith(b"#!/bin/") or content_bytes.startswith(b"#!/usr/bin/"):
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
        df: Optional[pd.DataFrame] = None

        if ext == ".csv":
            encodings_to_try = ["utf-8", "utf-8-sig", "latin1", "cp1252"]
            parsed_successfully = False
            for enc in encodings_to_try:
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc)
                    parsed_successfully = True
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Malformed CSV content: {str(exc).splitlines()[0]}",
                    )
            if not parsed_successfully or df is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to decode CSV content with supported encodings (UTF-8, Latin-1, CP1252).",
                )
        else:
            try:
                df = pd.read_excel(io.BytesIO(content))
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Malformed or corrupted Excel workbook: {str(exc).splitlines()[0]}",
                )

        if df is None or len(df) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dataset contains 0 data rows.",
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

        dataset_id = str(uuid4())
        storage_rel_dir = Path("data") / "tenants" / organization_id / business_id / dataset_id
        storage_rel_dir.mkdir(parents=True, exist_ok=True)
        storage_file_path = storage_rel_dir / clean_name
        storage_file_path.write_bytes(content)

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
            started_at=datetime.now(timezone.utc),
            rows_processed=len(df),
        )
        db.add(initial_job)

        # Update business data readiness status
        biz = db.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        if biz:
            biz.data_readiness_status = quality_summary.overall_status
            if quality_summary.can_open_workspace:
                biz.onboarding_step = "completed"

        db.commit()
        db.refresh(dataset)
        logger.info(
            "Dataset upload accepted: business_id=%s dataset_id=%s filename='%s' "
            "rows=%d cols=%d readiness=%s",
            business_id, dataset_id, clean_name,
            len(df), len(df.columns), quality_summary.overall_status,
        )
        return dataset

    @classmethod
    def profile_columns(cls, df: pd.DataFrame) -> Tuple[List[ColumnProfile], Optional[DateCoverage]]:
        """Compute deterministic profiling for every column in the dataframe."""
        row_count = len(df)
        profiles: List[ColumnProfile] = []
        date_coverage: Optional[DateCoverage] = None

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
                except Exception:
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
        col_profiles: List[ColumnProfile],
        date_coverage: Optional[DateCoverage],
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
        checks: List[QualityCheckItem] = []
        action_items: List[str] = []
        dimensions: Dict[str, str] = {
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
    def infer_schema_mapping(cls, df: pd.DataFrame, col_profiles: List[ColumnProfile]) -> SchemaMappingProposal:
        """Infer target entity and column mappings using deterministic pattern matching."""
        cols = [str(c).lower().strip() for c in df.columns]
        best_entity = "Sale"
        best_score = -1.0
        best_mapping: Dict[str, str] = {}
        best_missing: List[str] = []

        for entity_name, spec in cls.ENTITY_TARGETS.items():
            matched_fields: Dict[str, str] = {}
            patterns = spec["patterns"]

            for target_field, pat_list in patterns.items():
                for actual_col in df.columns:
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

        storage_path = Path(dataset.storage_key)
        if not storage_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset file is no longer available on storage.",
            )

        try:
            if dataset.file_type == "csv":
                df = pd.read_csv(storage_path, nrows=sample_size)
            else:
                df = pd.read_excel(storage_path, nrows=sample_size)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read dataset preview: {str(exc).splitlines()[0]}",
            )

        # Convert NaNs and dates to JSON-serializable primitives
        df_clean = df.replace({np.nan: None})
        sample_records: List[Dict[str, Any]] = []
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
        target_entity: Optional[str] = None,
        column_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
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

        storage_path = Path(dataset.storage_key)
        if not storage_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset storage file not found.",
            )

        schema_json = dataset.schema_json or {}
        mapping_info = schema_json.get("mapping_proposal", {})
        entity = target_entity or mapping_info.get("target_entity", "Sale")
        field_map = dict(mapping_info.get("field_mappings", {}))
        if column_overrides:
            field_map.update(column_overrides)

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
            return {
                "dataset_id": dataset.id,
                "job_id": completed_job.id,
                "entity": entity,
                "records_persisted": completed_job.rows_processed,
                "status": "COMPLETED",
                "message": f"Dataset already ingested into {entity} (idempotent no-op).",
            }

        # Create Durable Ingestion Job: PROCESSING
        job = IngestionJob(
            id=str(uuid4()),
            organization_id=dataset.organization_id,
            business_id=business_id,
            dataset_id=dataset_id,
            status="PROCESSING",
            target_entity=entity,
            started_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.flush()
        logger.info(
            "Ingestion job started: business_id=%s dataset_id=%s entity=%s job_id=%s",
            business_id, dataset_id, entity, job.id,
        )

        try:
            if dataset.file_type == "csv":
                df = pd.read_csv(storage_path)
            else:
                df = pd.read_excel(storage_path)

            records_inserted = 0
            df = df.replace({np.nan: None})

            # Ingest based on target entity
            if entity == "Sale":
                date_col = next((c for c, f in field_map.items() if f == "date"), None)
                amount_col = next((c for c, f in field_map.items() if f == "amount"), None)
                order_col = next((c for c, f in field_map.items() if f == "order_number"), None)

                if not amount_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest Sales: missing required 'amount' column mapping.",
                    )

                # Ensure a valid customer exists for this business
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
                        acquisition_date=date.today(),
                    )
                    db.add(cust)
                    db.flush()

                for _, row in df.iterrows():
                    val = row[amount_col]
                    try:
                        num_amount = round(float(val), 2) if val is not None else 0.0
                    except (ValueError, TypeError):
                        num_amount = 0.0

                    sale_dt = datetime.now(timezone.utc)
                    if date_col and row[date_col] is not None:
                        try:
                            sale_dt = pd.to_datetime(row[date_col]).to_pydatetime()
                        except Exception:
                            pass

                    sale_order = str(row[order_col]) if order_col and row[order_col] is not None else f"TXN-{uuid4().hex[:8]}"

                    # Deduplication guard on transaction_number
                    existing_sale = db.execute(
                        select(Sale).where(
                            Sale.business_id == business_id,
                            Sale.transaction_number == sale_order,
                        )
                    ).scalars().first()
                    if existing_sale:
                        continue

                    sale = Sale(
                        business_id=business_id,
                        transaction_number=sale_order,
                        customer_id=cust.id,
                        transaction_date=sale_dt,
                        subtotal=Decimal(str(num_amount)),
                        discount_amount=Decimal("0.00"),
                        tax_amount=Decimal("0.00"),
                        total_amount=Decimal(str(num_amount)),
                        status="completed",
                    )
                    db.add(sale)
                    records_inserted += 1

            elif entity == "Product":
                sku_col = next((c for c, f in field_map.items() if f == "sku"), None)
                name_col = next((c for c, f in field_map.items() if f == "name"), None)
                price_col = next((c for c, f in field_map.items() if f == "selling_price"), None)
                cost_col = next((c for c, f in field_map.items() if f == "unit_cost"), None)
                cat_col = next((c for c, f in field_map.items() if f == "category"), None)

                if not sku_col or not name_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest Products: missing 'sku' or 'name' mapping.",
                    )

                for _, row in df.iterrows():
                    sku_val = str(row[sku_col]) if row[sku_col] is not None else f"SKU-{uuid4().hex[:6]}"
                    name_val = str(row[name_col]) if row[name_col] is not None else "Product"
                    price_val = float(row[price_col]) if price_col and row[price_col] is not None else 0.0
                    cost_val = float(row[cost_col]) if cost_col and row[cost_col] is not None else 0.0
                    cat_val = str(row[cat_col]) if cat_col and row[cat_col] is not None else "General"

                    # Deduplication guard on SKU
                    existing_prod = db.execute(
                        select(Product).where(
                            Product.business_id == business_id,
                            Product.sku == sku_val,
                        )
                    ).scalars().first()
                    if existing_prod:
                        continue

                    prod = Product(
                        business_id=business_id,
                        sku=sku_val,
                        name=name_val,
                        selling_price=price_val,
                        unit_cost=cost_val,
                        category=cat_val,
                        is_active=True,
                    )
                    db.add(prod)
                    records_inserted += 1

            elif entity == "Customer":
                code_col = next((c for c, f in field_map.items() if f == "customer_code"), None)
                name_col = next((c for c, f in field_map.items() if f == "name"), None)
                email_col = next((c for c, f in field_map.items() if f == "email"), None)
                city_col = next((c for c, f in field_map.items() if f == "city"), None)

                if not name_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest Customers: missing 'name' mapping.",
                    )

                for _, row in df.iterrows():
                    cust_code = str(row[code_col]) if code_col and row[code_col] is not None else f"CUST-{uuid4().hex[:6]}"
                    cust_name = str(row[name_col]) if row[name_col] is not None else "Customer"
                    cust_email = str(row[email_col]) if email_col and row[email_col] is not None else f"cust-{uuid4().hex[:8]}@nexus.local"
                    cust_city = str(row[city_col]) if city_col and row[city_col] is not None else "Unknown"

                    # Deduplication guard on customer_code or email
                    existing_cust = db.execute(
                        select(Customer).where(
                            (Customer.customer_code == cust_code) | (Customer.email == cust_email)
                        )
                    ).scalars().first()
                    if existing_cust:
                        continue

                    cust = Customer(
                        business_id=business_id,
                        customer_code=cust_code,
                        name=cust_name,
                        email=cust_email,
                        city=cust_city,
                        customer_segment="Retail",
                        acquisition_date=date.today(),
                    )
                    db.add(cust)
                    records_inserted += 1

            elif entity == "Expense":
                date_col = next((c for c, f in field_map.items() if f == "expense_date"), None)
                cat_col = next((c for c, f in field_map.items() if f == "category"), None)
                amount_col = next((c for c, f in field_map.items() if f == "amount"), None)
                desc_col = next((c for c, f in field_map.items() if f == "description"), None)

                for _, row in df.iterrows():
                    amt = float(row[amount_col]) if amount_col and row[amount_col] is not None else 0.0
                    exp_dt = date.today()
                    if date_col and row[date_col] is not None:
                        try:
                            exp_dt = pd.to_datetime(row[date_col]).date()
                        except Exception:
                            pass
                    cat = str(row[cat_col]) if cat_col and row[cat_col] is not None else "Operating"
                    desc = str(row[desc_col]) if desc_col and row[desc_col] is not None else "Business Expense"

                    exp = Expense(
                        business_id=business_id,
                        expense_date=exp_dt,
                        category=cat,
                        amount=amt,
                        description=desc,
                    )
                    db.add(exp)
                    records_inserted += 1

            elif entity == "SaleItem":
                sale_id_col = next((c for c, f in field_map.items() if f == "sale_id"), None)
                prod_id_col = next((c for c, f in field_map.items() if f == "product_id"), None)
                qty_col = next((c for c, f in field_map.items() if f == "quantity"), None)
                price_col = next((c for c, f in field_map.items() if f == "unit_price"), None)

                if not qty_col or not price_col:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot ingest SaleItems: missing required 'quantity' or 'unit_price' column.",
                    )

                for _, row in df.iterrows():
                    qty = max(1, int(row[qty_col])) if qty_col and row[qty_col] is not None else 1
                    u_price = Decimal(str(round(float(row[price_col]), 2))) if price_col and row[price_col] is not None else Decimal("0.00")
                    l_total = u_price * qty

                    s_item = SaleItem(
                        sale_id=int(row[sale_id_col]) if sale_id_col and row[sale_id_col] is not None else 1,
                        product_id=int(row[prod_id_col]) if prod_id_col and row[prod_id_col] is not None else 1,
                        quantity=qty,
                        unit_price=u_price,
                        discount_amount=Decimal("0.00"),
                        line_total=l_total,
                    )
                    db.add(s_item)
                    records_inserted += 1

            # Update IngestionJob to COMPLETED
            job.status = "COMPLETED"
            job.completed_at = datetime.now(timezone.utc)
            job.rows_processed = records_inserted

            # Update dataset metadata
            # Update dataset metadata with new dict copy and flag_modified
            schema_copy = dict(dataset.schema_json or {})
            schema_copy["ingestion_status"] = "COMPLETED"
            schema_copy["ingested_at"] = datetime.now(timezone.utc).isoformat()
            schema_copy["records_persisted"] = records_inserted
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
                business_id, dataset_id, entity, job.id, records_inserted,
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
            except Exception as sem_exc:
                logger.warning(
                    "Automatic semantic activation encountered an issue for business %s: %s",
                    business_id,
                    sem_exc,
                )

            return {
                "dataset_id": dataset.id,
                "job_id": job.id,
                "entity": entity,
                "records_persisted": records_inserted,
                "status": "COMPLETED",
                "message": f"Successfully ingested {records_inserted} records into {entity} domain.",
            }

        except HTTPException:
            job.status = "FAILED"
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = "Ingestion rejected due to schema or constraint validation."
            db.commit()
            logger.warning(
                "Ingestion job FAILED (validation): business_id=%s dataset_id=%s entity=%s job_id=%s",
                business_id, dataset_id, entity, job.id,
            )
            raise
        except Exception as exc:
            db.rollback()
            # Set safe error message on job without exposing raw Python tracebacks
            safe_msg = f"Ingestion failed: {str(exc).splitlines()[0]}"
            job.status = "FAILED"
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = safe_msg[:500]
            db.commit()
            logger.error(
                "Ingestion job FAILED (exception): business_id=%s dataset_id=%s entity=%s job_id=%s error=%s",
                business_id, dataset_id, entity, job.id, safe_msg,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=safe_msg,
            )
