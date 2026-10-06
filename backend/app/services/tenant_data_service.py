"""Tenant Data Ingestion, Storage Isolation, and Data Readiness Profiling (Phase 15G & 15J).

Ensures:
- Secure file storage with tenant-isolated storage keys:
  organizations/{org_id}/businesses/{business_id}/datasets/{dataset_id}/...
- Filename sanitization, path traversal prevention, and extension whitelisting
- Automated CSV/XLSX profiling: schema detection, date coverage, quality warnings
- Real-time Data Readiness reporting for business owners
"""

import io
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tenant import Business, UploadedDataset


class TenantDataService:
    """Service orchestrating tenant file uploads, security validation, and data readiness."""

    MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
    ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
    PROHIBITED_EXTENSIONS = {".exe", ".py", ".sh", ".bat", ".bin", ".js", ".html", ".dll"}

    @classmethod
    def sanitize_filename(cls, filename: str) -> str:
        """Sanitize filename to prevent directory traversal and filesystem attacks."""
        if not filename:
            return f"upload_{str(uuid4())[:8]}.csv"
        # Strip null bytes and directory components
        clean = filename.replace("\x00", "").replace("/", "_").replace("\\", "_")
        clean = re.sub(r"\.\.+", ".", clean)
        # Keep alphanumeric, dots, underscores, hyphens
        clean = re.sub(r"[^a-zA-Z0-9._-]", "_", clean).strip("._")
        return clean or f"upload_{str(uuid4())[:8]}.csv"

    @classmethod
    def validate_file_security(cls, filename: str, content_bytes: bytes) -> None:
        """Validate file size, extension, and absence of executable payloads."""
        if len(content_bytes) > cls.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum allowable size of {cls.MAX_FILE_SIZE_BYTES // (1024*1024)} MB.",
            )

        ext = Path(filename).suffix.lower()
        if ext in cls.PROHIBITED_EXTENSIONS or ext not in cls.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file type '{ext}'. Only CSV and Excel (.xlsx, .xls) files are supported.",
            )

        if len(content_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

    @classmethod
    def profile_dataset(cls, df: pd.DataFrame, filename: str) -> tuple[dict[str, Any], dict[str, Any], str]:
        """
        Profile tabular dataset to assess schema, date coverage, and readiness status.
        
        Returns:
            (schema_json, quality_report_json, readiness_status)
        """
        row_count = len(df)
        col_count = len(df.columns)
        cols_lower = [str(c).lower().strip() for c in df.columns]

        schema_info: dict[str, Any] = {
            "columns": list(df.columns),
            "row_count": row_count,
            "column_count": col_count,
            "detected_domains": [],
            "date_coverage": None,
        }

        quality_report: dict[str, Any] = {
            "warnings": [],
            "errors": [],
            "metrics": {},
        }

        if row_count == 0:
            quality_report["errors"].append("Dataset contains 0 rows.")
            return schema_info, quality_report, "not_ready"

        # 1. Detect Domain Types
        has_sales = any(c in cols_lower for c in ["revenue", "sales", "subtotal", "total", "amount", "price"])
        has_dates = any(c in cols_lower for c in ["date", "transaction_date", "created_at", "order_date", "timestamp"])
        has_customers = any(c in cols_lower for c in ["customer", "customer_id", "email", "client"])
        has_products = any(c in cols_lower for c in ["product", "sku", "item", "product_name", "product_id"])

        if has_sales:
            schema_info["detected_domains"].append("sales")
        if has_customers:
            schema_info["detected_domains"].append("customers")
        if has_products:
            schema_info["detected_domains"].append("products")

        # 2. Date Range Detection
        date_col = next((c for c in df.columns if any(d in str(c).lower() for d in ["date", "time", "created"])), None)
        if date_col:
            try:
                date_series = pd.to_datetime(df[date_col], errors="coerce").dropna()
                if not date_series.empty:
                    schema_info["date_coverage"] = {
                        "column": date_col,
                        "min_date": date_series.min().isoformat(),
                        "max_date": date_series.max().isoformat(),
                        "total_valid_dates": len(date_series),
                    }
            except Exception:
                pass

        # 3. Quality & Null Checks
        null_counts = df.isnull().sum().to_dict()
        for col, null_val in null_counts.items():
            if null_val > 0:
                pct = round((null_val / row_count) * 100, 1)
                if pct > 20:
                    quality_report["warnings"].append(f"Column '{col}' has {pct}% missing values.")
                elif "id" in str(col).lower() and pct > 0:
                    quality_report["warnings"].append(f"{pct}% missing values in key column '{col}'.")

        # 4. Duplicate Rows
        duplicate_count = df.duplicated().sum()
        if duplicate_count > 0:
            quality_report["warnings"].append(f"Detected {duplicate_count} duplicate rows.")

        # 5. Determine Overall Readiness Status
        if not has_sales and not has_customers and not has_products:
            quality_report["warnings"].append("Could not identify retail domain columns (sales, customers, or products).")
            readiness_status = "ready_with_warnings"
        elif quality_report["errors"]:
            readiness_status = "not_ready"
        elif quality_report["warnings"]:
            readiness_status = "ready_with_warnings"
        else:
            readiness_status = "ready"

        quality_report["metrics"] = {
            "rows": row_count,
            "columns": col_count,
            "has_revenue_detected": has_sales,
            "has_dates_detected": date_col is not None,
            "readiness_status": readiness_status,
        }

        return schema_info, quality_report, readiness_status

    @classmethod
    def ingest_uploaded_file(
        cls,
        file: UploadFile,
        organization_id: str,
        business_id: str,
        session: Session,
    ) -> UploadedDataset:
        """
        Ingest, validate, store, and profile an uploaded customer data file.
        Enforces tenant-scoped storage paths and updates business data readiness.
        """
        raw_name = file.filename or "data.csv"
        clean_name = cls.sanitize_filename(raw_name)
        content = file.file.read()

        cls.validate_file_security(clean_name, content)

        # Parse with pandas
        ext = Path(clean_name).suffix.lower()
        try:
            if ext == ".csv":
                df = pd.read_csv(io.BytesIO(content))
            else:
                df = pd.read_excel(io.BytesIO(content))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse tabular file: {exc}",
            )

        # Profile dataset
        schema_json, quality_report_json, readiness_status = cls.profile_dataset(df, clean_name)

        # Secure Storage Path
        dataset_id = str(uuid4())
        storage_rel_dir = Path("data") / "tenants" / organization_id / business_id / dataset_id
        storage_rel_dir.mkdir(parents=True, exist_ok=True)
        storage_file_path = storage_rel_dir / clean_name
        storage_file_path.write_bytes(content)

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
            schema_json=schema_json,
            quality_report_json=quality_report_json,
            readiness_status=readiness_status,
        )
        session.add(dataset)

        # Update business readiness status
        biz = session.execute(
            select(Business).where(Business.id == business_id)
        ).scalar_one_or_none()
        if biz:
            biz.data_readiness_status = readiness_status
            biz.onboarding_step = "completed"

        session.commit()
        session.refresh(dataset)
        return dataset

    @classmethod
    def save_and_profile_file(
        cls,
        organization_id: str,
        business_id: str,
        filename: str,
        content: bytes,
        session: Session | None = None,
        db: Session | None = None,
        content_type: str | None = None,
    ) -> tuple[UploadedDataset, dict[str, Any]]:
        """
        Validate, isolate, profile, and record uploaded file in tenant storage.
        """
        s = session or db
        if not s:
            raise ValueError("Database session must be provided.")

        clean_name = cls.sanitize_filename(filename)
        cls.validate_file_security(clean_name, content)

        ext = Path(clean_name).suffix.lower()
        try:
            if ext == ".csv":
                df = pd.read_csv(io.BytesIO(content))
            else:
                df = pd.read_excel(io.BytesIO(content))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse tabular file: {exc}",
            )

        schema_json, quality_report_json, readiness_status = cls.profile_dataset(df, clean_name)

        dataset_id = str(uuid4())
        storage_rel_dir = Path("data") / "tenants" / organization_id / business_id / dataset_id
        storage_rel_dir.mkdir(parents=True, exist_ok=True)
        storage_file_path = storage_rel_dir / clean_name
        storage_file_path.write_bytes(content)

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
            schema_json=schema_json,
            quality_report_json=quality_report_json,
            readiness_status=readiness_status,
        )
        s.add(dataset)

        biz = s.execute(
            select(Business).where(Business.id == business_id)
        ).scalar_one_or_none()
        if biz:
            biz.data_readiness_status = readiness_status
            biz.onboarding_step = "completed"

        s.commit()
        s.refresh(dataset)
        return dataset, quality_report_json

    @classmethod
    def get_data_readiness(
        cls,
        session: Session | None = None,
        business_id: str | None = None,
        db: Session | None = None,
    ) -> dict[str, Any]:
        """Assess overall data readiness for a business workspace."""
        s = session or db
        if not s:
            raise ValueError("Database session must be provided.")
        if not business_id:
            return {
                "business_id": None,
                "dataset_count": 0,
                "total_datasets": 0,
                "total_rows": 0,
                "total_columns": 0,
                "status": "not_ready",
                "domains_covered": [],
                "summary": "0 datasets • 0 rows ingested.",
                "datasets": [],
            }

        # 1. Query uploaded datasets scoped strictly to tenant
        stmt = select(UploadedDataset).where(UploadedDataset.business_id == business_id)
        datasets = s.execute(stmt).scalars().all()
        uploaded_rows = sum(d.row_count or 0 for d in datasets)
        total_cols = sum(d.column_count or 0 for d in datasets)

        # 2. Query persisted domain tables scoped strictly to tenant via DataProfiler
        from app.data.profiling.profiler import DataProfiler
        profiler = DataProfiler(db=s, business_id=business_id)
        summaries = profiler.get_table_summaries()
        persisted_rows = sum(item.row_count for item in summaries)
        tables_with_data = [item.table_name for item in summaries if item.row_count > 0]

        # 3. Reconcile dataset count and total rows
        dataset_count = len(datasets) if len(datasets) > 0 else len(tables_with_data)
        total_rows = max(uploaded_rows, persisted_rows)

        # 4. Status determination (case-insensitive check)
        statuses = [d.readiness_status.lower() for d in datasets if d.readiness_status]
        biz = s.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        biz_status = biz.data_readiness_status.lower() if (biz and biz.data_readiness_status) else ""

        overall_status = "not_ready"
        if total_rows == 0 and dataset_count == 0:
            overall_status = "not_ready"
        elif "ready" in statuses or biz_status in ("ready", "ready_with_warnings") or (total_rows > 0 and len(datasets) > 0):
            overall_status = "ready"
        elif "ready_with_warnings" in statuses:
            overall_status = "ready_with_warnings"
        elif total_rows > 0:
            overall_status = "ready"

        # Keep business record aligned with current readiness status
        if biz and overall_status == "ready" and biz_status not in ("ready", "ready_with_warnings"):
            biz.data_readiness_status = "ready"
            s.add(biz)
            s.flush()

        summary = f"{dataset_count} dataset(s) • {total_rows} rows ingested"
        if tables_with_data:
            summary += f" across {len(tables_with_data)} domain(s)."
        else:
            summary += "."

        return {
            "business_id": business_id,
            "dataset_count": dataset_count,
            "total_datasets": dataset_count,
            "total_rows": total_rows,
            "total_columns": total_cols,
            "status": overall_status,
            "domains_covered": tables_with_data,
            "summary": summary,
            "datasets": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "file_type": d.file_type,
                    "rows": d.row_count,
                    "columns": d.column_count,
                    "readiness_status": d.readiness_status.lower() if d.readiness_status else "ready",
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in datasets
            ],
        }


