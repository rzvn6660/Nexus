"""NEXUS Phase 31B Step 3 — Ingress and Upload Ingestion Limits Tests.

Validates:
1. Reconciled 50 MB upload limits across Nginx, Settings, DataGatewayService, and TenantDataService.
2. Ingress proxy security configuration (buffer sizes, timeouts, and body size limits in nginx.conf).
3. HTTP 413 Content Too Large rejection for payloads exceeding 50 MB.
4. HTTP 400 Bad Request rejection for empty (0-byte) payloads.
5. Defense-in-depth security rejection for executable binaries (MZ, ELF signatures).
6. Defense-in-depth security rejection for shell scripts (shebang signatures).
7. HTTP 415 rejection for prohibited extensions across all gateway and tenant endpoints.
8. Proper tenant path isolation and path-traversal defense for tabular files.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.services.data_gateway_service import DataGatewayService
from app.services.tenant_data_service import TenantDataService


# ---------------------------------------------------------------------------
# 1. Configuration & Alignment Verification
# ---------------------------------------------------------------------------


def test_upload_limits_reconciled_across_services() -> None:
    """Verify that backend settings, DataGatewayService, and TenantDataService share identical 50 MB limits."""
    expected_limit = 50 * 1024 * 1024  # 50 MB = 52,428,800 bytes

    assert settings.DATA_UPLOAD_MAX_BYTES == expected_limit
    assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE_MB == 50
    assert DataGatewayService.MAX_UPLOAD_BYTES == expected_limit
    assert DataGatewayService.MAX_FILE_SIZE_BYTES == expected_limit
    assert TenantDataService.MAX_FILE_SIZE_BYTES == expected_limit
    assert TenantDataService.MAX_UPLOAD_BYTES == expected_limit


def test_nginx_ingress_configuration_aligned_with_backend() -> None:
    """Verify nginx.conf contains matching 50M client_max_body_size and DoS timeout protections."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    nginx_conf_path = repo_root / "infra" / "docker" / "nginx.conf"

    assert nginx_conf_path.exists(), f"nginx.conf not found at {nginx_conf_path}"
    content = nginx_conf_path.read_text(encoding="utf-8")

    # Ingress body size matching 50M backend limit
    assert "client_max_body_size 50M;" in content, "nginx.conf client_max_body_size must be 50M"

    # Slowloris and buffer protections
    assert "client_body_buffer_size 128k;" in content
    assert "client_header_timeout 30s;" in content
    assert "client_body_timeout 60s;" in content

    # Backend proxy timeouts for large file processing
    assert "proxy_read_timeout 120s;" in content
    assert "proxy_send_timeout 120s;" in content


# ---------------------------------------------------------------------------
# 2. Oversized and Empty Upload Rejection
# ---------------------------------------------------------------------------


def test_tenant_data_service_rejects_oversized_file() -> None:
    """TenantDataService must reject files exceeding 50 MB with HTTP 413."""
    oversized = b"x" * (50 * 1024 * 1024 + 1)
    with pytest.raises(HTTPException) as exc_info:
        TenantDataService.validate_file_security("valid_sales.csv", oversized)
    assert exc_info.value.status_code == 413
    assert "exceeds maximum allowable size" in exc_info.value.detail


def test_data_gateway_service_rejects_oversized_file() -> None:
    """DataGatewayService must reject files exceeding 50 MB with HTTP 413."""
    oversized = b"x" * (50 * 1024 * 1024 + 1)
    with pytest.raises(HTTPException) as exc_info:
        DataGatewayService.validate_file_security("valid_sales.csv", oversized)
    assert exc_info.value.status_code == 413
    assert "exceeds maximum allowable limit" in exc_info.value.detail


def test_empty_files_rejected_across_services() -> None:
    """Empty files (0 bytes) must be rejected with HTTP 400 across both services."""
    for svc in [DataGatewayService, TenantDataService]:
        with pytest.raises(HTTPException) as exc_info:
            svc.validate_file_security("empty.csv", b"")
        assert exc_info.value.status_code == 400
        assert "empty" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 3. Executable and Shell Script Payload Rejection (Defense-in-Depth)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("svc", [DataGatewayService, TenantDataService])
def test_executable_binary_magic_signatures_rejected(svc) -> None:
    """Files disguised as CSV/XLSX but containing Windows PE (MZ) or Linux ELF magic bytes must be rejected."""
    # Windows PE header (MZ) disguised as .csv
    mz_payload = b"MZ\x90\x00\x03\x00\x00\x00fake_binary_payload"
    with pytest.raises(HTTPException) as exc_info:
        svc.validate_file_security("malicious_data.csv", mz_payload)
    assert exc_info.value.status_code == 400
    assert "Executable binary format rejected" in exc_info.value.detail

    # Linux ELF header disguised as .xlsx
    elf_payload = b"\x7fELF\x02\x01\x01\x00fake_elf_binary"
    with pytest.raises(HTTPException) as exc_info:
        svc.validate_file_security("transactions.xlsx", elf_payload)
    assert exc_info.value.status_code == 400
    assert "Executable binary format rejected" in exc_info.value.detail


@pytest.mark.parametrize("svc", [DataGatewayService, TenantDataService])
def test_shell_script_payloads_rejected(svc) -> None:
    """Files with script shebangs disguised as CSV must be rejected with HTTP 400."""
    script_payload = b"#!/bin/bash\nrm -rf /app/data\n"
    with pytest.raises(HTTPException) as exc_info:
        svc.validate_file_security("orders.csv", script_payload)
    assert exc_info.value.status_code == 400
    assert "Shell script execution format rejected" in exc_info.value.detail

    usr_script = b"#!/usr/bin/env python3\nimport os; os.system('echo hacked')\n"
    with pytest.raises(HTTPException) as exc_info:
        svc.validate_file_security("inventory.csv", usr_script)
    assert exc_info.value.status_code == 400
    assert "Shell script execution format rejected" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 4. Prohibited Extensions Whitelist Enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("svc", [DataGatewayService, TenantDataService])
@pytest.mark.parametrize("bad_ext", [
    ".exe", ".py", ".sh", ".bat", ".bin", ".js", ".html", ".dll",
    ".cmd", ".vbs", ".ps1", ".com", ".scr", ".msi", ".tar", ".gz"
])
def test_prohibited_and_unsupported_extensions_rejected(svc, bad_ext: str) -> None:
    """Any non-CSV/XLSX extension must be rejected with HTTP 415 Unsupported Media Type."""
    dummy_content = b"col1,col2\nval1,val2\n"
    with pytest.raises(HTTPException) as exc_info:
        svc.validate_file_security(f"payload{bad_ext}", dummy_content)
    assert exc_info.value.status_code == 415
    assert "unsupported" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 5. Legitimate Tabular Files Accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("svc", [DataGatewayService, TenantDataService])
def test_valid_csv_and_excel_accepted(svc) -> None:
    """Legitimate CSV and XLSX files must pass validation without raising exceptions."""
    valid_csv = b"transaction_date,amount,customer_id\n2026-01-01,150.00,CUST001\n"
    # Should not raise
    svc.validate_file_security("valid_transactions.csv", valid_csv)

    # Valid XLSX mock payload (not starting with MZ or ELF or shebang)
    valid_xlsx_dummy = b"PK\x03\x04\x14\x00\x06\x00mock_zip_xml_excel_payload"
    svc.validate_file_security("financial_report.xlsx", valid_xlsx_dummy)
    svc.validate_file_security("historical.xls", valid_xlsx_dummy)


# ---------------------------------------------------------------------------
# 6. Filename Sanitization and Path Traversal Protection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("svc", [DataGatewayService, TenantDataService])
def test_filename_sanitization_blocks_path_traversal(svc) -> None:
    """Filenames with directory traversal characters must be sanitized safely."""
    malicious_names = [
        ("../../etc/passwd.csv", "etc_passwd.csv"),
        ("..\\..\\windows\\system32\\cmd.csv", "windows_system32_cmd.csv"),
        ("\x00secret.csv", "secret.csv"),
        ("....//nested/data.csv", "nested_data.csv"),
    ]
    for raw_name, _ in malicious_names:
        clean = svc.sanitize_filename(raw_name)
        assert "/" not in clean
        assert "\\" not in clean
        assert "\x00" not in clean
        assert not clean.startswith("..")
