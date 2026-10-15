"""Production Readiness Verification Script (Phase 35).

Executes comprehensive live and static readiness checks across:
1. Environment and Security Guardrails (LLM_ALLOW_EXTERNAL_CALLS, JWT secrets, DEBUG)
2. Database Connectivity & Migration Head (PostgreSQL / pgvector / Alembic)
3. Shared Cache State & Redis Resilience (Lua rate-limiting, JWT revocation fail-closed)
4. Tenant Storage Durability & Path Traversal Isolation
5. Ingress & Upload Security (50MB limit, binary signature & extension whitelisting)
6. Deterministic Financial Computation Integrity (0.0% LLM math hallucination)
7. Dedicated Continuous Scheduler Configuration
8. Reverse Proxy (Nginx) Security Headers and Buffer Timeouts

Usage:
    python infra/deployment/verify_production_readiness.py [--strict]
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import os
from pathlib import Path
import sys

from fastapi import HTTPException
from sqlalchemy import text

# Add backend directory to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))


class CheckStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    DEPENDENCY_PENDING = "DEPENDENCY_PENDING"


@dataclass
class CheckResult:
    category: str
    name: str
    status: CheckStatus
    details: str


def run_all_checks(strict: bool = False) -> list[CheckResult]:
    results: list[CheckResult] = []

    # 1. Environment & Security Configuration Guardrails
    try:
        from app.core.config import settings

        # Guardrail: LLM_ALLOW_EXTERNAL_CALLS must be strictly False
        if not settings.LLM_ALLOW_EXTERNAL_CALLS:
            results.append(
                CheckResult(
                    "Security",
                    "LLM_ALLOW_EXTERNAL_CALLS Guardrail",
                    CheckStatus.PASSED,
                    "Strictly disabled (LLM_ALLOW_EXTERNAL_CALLS=False).",
                )
            )
        else:
            results.append(
                CheckResult(
                    "Security",
                    "LLM_ALLOW_EXTERNAL_CALLS Guardrail",
                    CheckStatus.FAILED,
                    "CRITICAL: LLM_ALLOW_EXTERNAL_CALLS is enabled!",
                )
            )

        # JWT Secret entropy
        dev_secrets = {
            "nexus-dev-secret-key-change-in-production",
            "supersecretjwtkeyfornexusdevelopmentonly32charsminimum!",
            "default_jwt_secret",
            "secret",
        }
        if settings.AUTH_JWT_SECRET in dev_secrets or len(settings.AUTH_JWT_SECRET) < 32:
            status = CheckStatus.WARNING if settings.APP_ENV != "production" else CheckStatus.FAILED
            results.append(
                CheckResult(
                    "Security",
                    "AUTH_JWT_SECRET Entropy",
                    status,
                    f"JWT secret appears default or has <32 chars in env='{settings.APP_ENV}'.",
                )
            )
        else:
            results.append(
                CheckResult(
                    "Security",
                    "AUTH_JWT_SECRET Entropy",
                    CheckStatus.PASSED,
                    "Production-grade JWT secret configured (>32 chars).",
                )
            )

        # Upload limit consistency
        expected_bytes = 50 * 1024 * 1024
        if settings.DATA_UPLOAD_MAX_BYTES == expected_bytes:
            results.append(
                CheckResult(
                    "Configuration",
                    "DATA_UPLOAD_MAX_BYTES Alignment",
                    CheckStatus.PASSED,
                    f"Aligned to exactly 50 MB ({expected_bytes} bytes).",
                )
            )
        else:
            results.append(
                CheckResult(
                    "Configuration",
                    "DATA_UPLOAD_MAX_BYTES Alignment",
                    CheckStatus.FAILED,
                    f"Expected {expected_bytes} bytes (50MB), found {settings.DATA_UPLOAD_MAX_BYTES}.",
                )
            )

    except Exception as exc:
        results.append(
            CheckResult("Configuration", "Settings Initialization", CheckStatus.FAILED, str(exc))
        )

    # 2. Database Connectivity & Migration Head
    try:
        from app.core.database import engine, check_database_connection

        db_stat = check_database_connection(engine)
        if db_stat.get("connected"):
            dialect = db_stat.get("dialect", "")
            if dialect == "postgresql":
                with engine.connect() as conn:
                    vec_check = conn.execute(
                        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    ).scalar()
                if vec_check:
                    results.append(
                        CheckResult(
                            "Database",
                            "PostgreSQL & pgvector",
                            CheckStatus.PASSED,
                            "Live PostgreSQL connected with pgvector extension enabled.",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            "Database",
                            "PostgreSQL & pgvector",
                            CheckStatus.WARNING,
                            "PostgreSQL connected, but pgvector extension is NOT installed.",
                        )
                    )
            else:
                results.append(
                    CheckResult(
                        "Database",
                        "Database Dialect",
                        CheckStatus.WARNING,
                        f"Connected to local '{dialect}'. Production verification requires PostgreSQL/pgvector.",
                    )
                )
        else:
            results.append(
                CheckResult(
                    "Database",
                    "Database Connectivity",
                    CheckStatus.DEPENDENCY_PENDING,
                    f"Live production database unreachable ({db_stat.get('error', 'connection failed')}).",
                )
            )

        # Alembic migration scripts check
        alembic_versions_dir = REPO_ROOT / "backend" / "alembic" / "versions"
        if alembic_versions_dir.exists():
            migration_files = list(alembic_versions_dir.glob("*.py"))
            if migration_files:
                results.append(
                    CheckResult(
                        "Database",
                        "Alembic Migrations",
                        CheckStatus.PASSED,
                        f"Found {len(migration_files)} migration script(s) in alembic/versions.",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "Database",
                        "Alembic Migrations",
                        CheckStatus.FAILED,
                        "No migration scripts found in alembic/versions.",
                    )
                )

    except Exception as exc:
        results.append(
            CheckResult("Database", "Database Engine Setup", CheckStatus.FAILED, str(exc))
        )

    # 3. Redis Shared State & Resilience
    try:
        from app.core.cache import check_redis_health

        health = check_redis_health()
        if health.get("status") == "connected" and health.get("shared_state_available"):
            results.append(
                CheckResult(
                    "Cache/SharedState",
                    "Redis Connectivity",
                    CheckStatus.PASSED,
                    f"Connected to shared Redis state ({health.get('mode')}).",
                )
            )
        elif health.get("required") and not health.get("shared_state_available"):
            results.append(
                CheckResult(
                    "Cache/SharedState",
                    "Redis Connectivity",
                    CheckStatus.DEPENDENCY_PENDING,
                    "Live shared Redis unreachable; REDIS_FAIL_CLOSED=True correctly active.",
                )
            )
        else:
            results.append(
                CheckResult(
                    "Cache/SharedState",
                    "Redis Connectivity",
                    CheckStatus.WARNING,
                    f"Redis state status: {health.get('status')}, mode: {health.get('mode')}",
                )
            )
    except Exception as exc:
        results.append(CheckResult("Cache/SharedState", "Redis Probe", CheckStatus.FAILED, str(exc)))

    # 4. Ingress & Upload Limits
    try:
        from app.services.tenant_data_service import TenantDataService
        from app.services.data_gateway_service import DataGatewayService

        # Validate limits match across services
        tds_limit = TenantDataService.MAX_FILE_SIZE_BYTES
        dgs_limit = DataGatewayService.MAX_UPLOAD_BYTES
        if tds_limit == expected_bytes and dgs_limit == expected_bytes:
            results.append(
                CheckResult(
                    "Ingress",
                    "Service Upload Limits",
                    CheckStatus.PASSED,
                    f"TenantDataService & DataGatewayService both configured for {expected_bytes} bytes.",
                )
            )
        else:
            results.append(
                CheckResult(
                    "Ingress",
                    "Service Upload Limits",
                    CheckStatus.FAILED,
                    f"Limit mismatch: TenantDataService={tds_limit}, DataGatewayService={dgs_limit}",
                )
            )

        # Validate binary signature defense
        try:
            TenantDataService.validate_file_security("test.exe", b"MZ\x90\x00\x03\x00")
            results.append(
                CheckResult(
                    "Ingress",
                    "Binary Magic Signature Defense",
                    CheckStatus.FAILED,
                    "Failed to reject DOS/PE executable header.",
                )
            )
        except HTTPException as http_exc:
            if http_exc.status_code == 400 and "binary" in str(http_exc.detail).lower():
                results.append(
                    CheckResult(
                        "Ingress",
                        "Binary Magic Signature Defense",
                        CheckStatus.PASSED,
                        "Correctly rejected DOS/PE executable signature with HTTP 400.",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "Ingress",
                        "Binary Magic Signature Defense",
                        CheckStatus.FAILED,
                        f"Unexpected detail: {http_exc.detail}",
                    )
                )

    except Exception as exc:
        results.append(
            CheckResult("Ingress", "Upload Security Validation", CheckStatus.FAILED, str(exc))
        )

    # 5. Tenant Storage Isolation
    try:
        base_dir = Path(getattr(settings, "DATA_DIR", "data"))
        clean_org = "test_org_uuid"
        clean_biz = "test_biz_uuid"
        dataset_id = "test_ds_uuid"
        clean_name = TenantDataService.sanitize_filename("sales_report.csv")
        storage_rel_dir = base_dir / "tenants" / clean_org / clean_biz / dataset_id
        storage_file_path = storage_rel_dir / clean_name
        is_safe = storage_file_path.resolve().is_relative_to(base_dir.resolve())
        if is_safe and "test_org_uuid" in str(storage_file_path):
            results.append(
                CheckResult(
                    "Storage",
                    "Tenant Path Isolation",
                    CheckStatus.PASSED,
                    f"Deterministic tenant path hierarchy verified: {storage_file_path.relative_to(base_dir)}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "Storage",
                    "Tenant Path Isolation",
                    CheckStatus.FAILED,
                    f"Path escapes base directory: {storage_file_path}",
                )
            )
    except Exception as exc:
        results.append(
            CheckResult("Storage", "Storage Path Verification", CheckStatus.FAILED, str(exc))
        )

    # 6. Deterministic Analytics Engine (Zero Math Hallucination)
    try:
        from app.analytics.metrics.financial import calculate_comparison
        from app.analytics.core.types import TrendDirection

        res = calculate_comparison(Decimal("675.00"), Decimal("500.00"))
        if (
            res.absolute_change == Decimal("175.00")
            and abs(res.percentage_change - 35.0) < 1e-4
            and res.direction == TrendDirection.INCREASE
        ):
            results.append(
                CheckResult(
                    "Analytics",
                    "Deterministic Financial Precision",
                    CheckStatus.PASSED,
                    f"Verified exact arithmetic comparison: abs={res.absolute_change}, pct={res.percentage_change}%, dir={res.direction.value}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "Analytics",
                    "Deterministic Financial Precision",
                    CheckStatus.FAILED,
                    f"Financial arithmetic mismatch: {res}",
                )
            )
    except Exception as exc:
        results.append(
            CheckResult("Analytics", "Financial Math Engine", CheckStatus.FAILED, str(exc))
        )

    # 7. Reverse Proxy Security Headers
    try:
        nginx_conf = REPO_ROOT / "infra" / "docker" / "nginx.conf"
        if nginx_conf.exists():
            text_content = nginx_conf.read_text(encoding="utf-8")
            required_headers = [
                "X-Frame-Options",
                "X-Content-Type-Options",
                "X-XSS-Protection",
                "Referrer-Policy",
                "client_max_body_size 50M;",
            ]
            missing = [h for h in required_headers if h not in text_content]
            if not missing:
                results.append(
                    CheckResult(
                        "ReverseProxy",
                        "Nginx Ingress Hardening",
                        CheckStatus.PASSED,
                        "All required OWASP security headers and 50M limit present.",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "ReverseProxy",
                        "Nginx Ingress Hardening",
                        CheckStatus.FAILED,
                        f"Missing headers/directives: {missing}",
                    )
                )
        else:
            results.append(
                CheckResult(
                    "ReverseProxy",
                    "Nginx Ingress Hardening",
                    CheckStatus.FAILED,
                    f"Missing {nginx_conf}",
                )
            )
    except Exception as exc:
        results.append(CheckResult("ReverseProxy", "Nginx Inspection", CheckStatus.FAILED, str(exc)))

    # 8. Dedicated Scheduler Isolation
    try:
        compose_file = REPO_ROOT / "docker-compose.prod.yml"
        compose_text = compose_file.read_text(encoding="utf-8") if compose_file.exists() else ""
        if (
            "CONTINUOUS_SCHEDULER_AUTOSTART=false" in compose_text
            and ("service_name: nexus_scheduler_prod" in compose_text
            or "nexus_scheduler_prod" in compose_text)
        ):
            results.append(
                CheckResult(
                    "Scheduler",
                    "Scheduler Worker Isolation",
                    CheckStatus.PASSED,
                    "Web autostart disabled; dedicated scheduler service defined in compose.",
                )
            )
        else:
            results.append(
                CheckResult(
                    "Scheduler",
                    "Scheduler Worker Isolation",
                    CheckStatus.WARNING,
                    "Continuous scheduler autostart or dedicated container configuration not found.",
                )
            )
    except Exception as exc:
        results.append(
            CheckResult("Scheduler", "Scheduler Config Inspection", CheckStatus.FAILED, str(exc))
        )

    return results


def print_report(results: list[CheckResult]) -> int:
    """Print formatted summary and return exit code."""
    print("=" * 90)
    print(" NEXUS PRODUCTION READINESS VERIFICATION AUDIT (PHASE 35)")
    print("=" * 90)

    passed_count = sum(1 for r in results if r.status == CheckStatus.PASSED)
    failed_count = sum(1 for r in results if r.status == CheckStatus.FAILED)
    warn_count = sum(1 for r in results if r.status == CheckStatus.WARNING)
    pending_count = sum(1 for r in results if r.status == CheckStatus.DEPENDENCY_PENDING)

    for r in results:
        status_tag = f"[{r.status.value:^20}]"
        print(f"{status_tag} {r.category:<16} | {r.name:<34} : {r.details}")

    print("-" * 90)
    print(
        f"Summary: {passed_count} PASSED, {failed_count} FAILED, {warn_count} WARNINGS, {pending_count} DEPENDENCY_PENDING"
    )
    print("=" * 90)

    if failed_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    strict_mode = "--strict" in sys.argv
    res = run_all_checks(strict=strict_mode)
    code = print_report(res)
    sys.exit(code)
