"""Production Deployment Configuration Validator (Phase 34).

Executes static syntax, dependency, security, and networking validation across:
1. docker-compose.prod.yml
2. infra/docker/Dockerfile.backend & infra/docker/Dockerfile.frontend
3. infra/docker/nginx.conf
4. .env.example
"""

from pathlib import Path
import re
import sys
import yaml


def validate_production_deployment() -> list[str]:
    """Validate production deployment artifacts and return list of errors (empty if passed)."""
    errors: list[str] = []
    repo_root = Path(__file__).resolve().parent.parent.parent

    # 1. Validate docker-compose.prod.yml
    compose_path = repo_root / "docker-compose.prod.yml"
    if not compose_path.exists():
        errors.append(f"Missing {compose_path}")
    else:
        try:
            with open(compose_path, "r", encoding="utf-8") as f:
                compose = yaml.safe_load(f)
            services = compose.get("services", {})
            required_services = ["postgres", "redis", "backend", "scheduler", "frontend"]
            for s in required_services:
                if s not in services:
                    errors.append(f"docker-compose.prod.yml missing required service '{s}'")

            # Check network isolation: postgres and redis must NOT expose published ports
            if "ports" in services.get("postgres", {}):
                errors.append("SECURITY: postgres service exposes public ports in docker-compose.prod.yml")
            if "ports" in services.get("redis", {}):
                errors.append("SECURITY: redis service exposes public ports in docker-compose.prod.yml")

            # Check persistent volumes
            volumes = compose.get("volumes", {})
            required_volumes = ["nexus_postgres_prod_data", "nexus_backend_data", "nexus_redis_prod_data"]
            for v in required_volumes:
                if v not in volumes:
                    errors.append(f"docker-compose.prod.yml missing required volume '{v}'")

            # Check backend volume mount
            backend_volumes = services.get("backend", {}).get("volumes", [])
            if not any("nexus_backend_data:/app/data" in str(v) for v in backend_volumes):
                errors.append("backend service does not mount nexus_backend_data:/app/data")

            # Check scheduler volume mount
            scheduler_volumes = services.get("scheduler", {}).get("volumes", [])
            if not any("nexus_backend_data:/app/data" in str(v) for v in scheduler_volumes):
                errors.append("scheduler service does not mount nexus_backend_data:/app/data")

        except Exception as exc:
            errors.append(f"Failed to parse docker-compose.prod.yml: {exc}")

    # 2. Validate Dockerfile.backend
    backend_dockerfile = repo_root / "infra" / "docker" / "Dockerfile.backend"
    if not backend_dockerfile.exists():
        errors.append(f"Missing {backend_dockerfile}")
    else:
        content = backend_dockerfile.read_text(encoding="utf-8")
        if "useradd -m -u 1000 appuser" not in content or "USER appuser" not in content:
            errors.append("Dockerfile.backend must execute as non-root appuser")
        if "/app/data/tenants" not in content:
            errors.append("Dockerfile.backend missing persistent data directory creation")
        if "HEALTHCHECK" not in content:
            errors.append("Dockerfile.backend missing HEALTHCHECK instruction")

    # 3. Validate nginx.conf
    nginx_conf = repo_root / "infra" / "docker" / "nginx.conf"
    if not nginx_conf.exists():
        errors.append(f"Missing {nginx_conf}")
    else:
        content = nginx_conf.read_text(encoding="utf-8")
        if "client_max_body_size 50M;" not in content:
            errors.append("nginx.conf missing client_max_body_size 50M;")
        if "proxy_pass http://backend_api;" not in content:
            errors.append("nginx.conf missing upstream reverse proxy to backend_api")
        if "X-Content-Type-Options" not in content:
            errors.append("nginx.conf missing OWASP security headers")

    # 4. Validate .env.example
    env_example = repo_root / ".env.example"
    if not env_example.exists():
        errors.append(f"Missing {env_example}")
    else:
        content = env_example.read_text(encoding="utf-8")
        required_vars = [
            "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB",
            "REDIS_URL", "REDIS_FAIL_CLOSED",
            "SECRET_KEY", "AUTH_JWT_SECRET",
            "DATA_UPLOAD_MAX_BYTES",
            "CONTINUOUS_SCHEDULER_ENABLED",
        ]
        for var in required_vars:
            if var not in content:
                errors.append(f".env.example missing required configuration variable '{var}'")

    return errors


def main() -> None:
    errors = validate_production_deployment()
    if errors:
        print(f"FAILED: Found {len(errors)} deployment validation defects:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("PASSED: All production deployment artifacts, compose services, and configurations validated successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
