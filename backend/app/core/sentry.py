"""Sentry Error Tracking and Performance Monitoring Integration (Phase 32A).

Provides optional, safe error reporting for API and background scheduler processes.
Enforces strict sanitization to prevent sensitive user, business, credential,
and payload data from leaking to external monitoring services.
"""

from typing import Any
from urllib.parse import parse_qsl, urlencode

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("nexus.sentry")

# Substrings that mark a dictionary key, header, or query param as containing sensitive data
SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "secret",
    "token",
    "key",
    "auth",
    "cookie",
    "credential",
    "hash",
    "session",
    "jwt",
    "content",
    "upload",
    "dataset",
    "body",
)

# Standard sensitive HTTP headers requiring redaction
SENSITIVE_HEADERS = {
    "authorization",
    "x-api-key",
    "cookie",
    "set-cookie",
    "x-metrics-token",
    "proxy-authorization",
}


def is_sensitive_key(key: Any) -> bool:
    """Return True if string representation of key matches sensitive patterns."""
    if not isinstance(key, str):
        key = str(key)
    key_lower = key.lower()
    return any(sub in key_lower for sub in SENSITIVE_KEY_SUBSTRINGS)


def scrub_sensitive_dict(data: Any, depth: int = 0, max_depth: int = 8) -> Any:
    """Recursively redact sensitive keys and values from dictionaries, lists, or tuples."""
    if depth > max_depth:
        return "[MAX_DEPTH_REACHED]"

    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            k_str = str(k)
            if is_sensitive_key(k_str) or k_str.lower() in SENSITIVE_HEADERS:
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = scrub_sensitive_dict(v, depth + 1, max_depth)
        return scrubbed
    elif isinstance(data, (list, tuple)):
        scrubbed_list = [scrub_sensitive_dict(item, depth + 1, max_depth) for item in data]
        return type(data)(scrubbed_list)
    return data


def scrub_query_string(query_string: str) -> str:
    """Mask sensitive query parameter values while preserving structure."""
    if not query_string:
        return ""
    try:
        pairs = parse_qsl(query_string, keep_blank_values=True)
        sanitized = []
        for k, v in pairs:
            if is_sensitive_key(k):
                sanitized.append((k, "[REDACTED]"))
            else:
                sanitized.append((k, v))
        return urlencode(sanitized)
    except Exception:
        return "[REDACTED_QUERY]"


def before_send_handler(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Scrub sensitive business data, credentials, and request bodies before sending to Sentry."""
    try:
        # 1. Sanitize request information if present
        request = event.get("request")
        if isinstance(request, dict):
            # Strict policy: Never capture request bodies
            if "data" in request:
                request["data"] = "[REDACTED_REQUEST_BODY]"

            # Sanitize request headers
            headers = request.get("headers")
            if isinstance(headers, dict):
                request["headers"] = scrub_sensitive_dict(headers)

            # Sanitize cookies
            if "cookies" in request:
                request["cookies"] = "[REDACTED_COOKIES]"

            # Sanitize query parameters
            query_string = request.get("query_string")
            if isinstance(query_string, str):
                request["query_string"] = scrub_query_string(query_string)

        # 2. Sanitize user context (remove PII like email/username/IP)
        user = event.get("user")
        if isinstance(user, dict):
            event["user"] = {
                k: ("[REDACTED]" if is_sensitive_key(k) else v)
                for k, v in user.items()
                if k not in ("email", "username", "ip_address")
            }

        # 3. Sanitize extra data and contexts
        for section in ("extra", "contexts"):
            if section in event and isinstance(event[section], dict):
                event[section] = scrub_sensitive_dict(event[section])

        # 4. Sanitize breadcrumbs
        breadcrumbs = event.get("breadcrumbs")
        if isinstance(breadcrumbs, dict) and "values" in breadcrumbs:
            for crumb in breadcrumbs.get("values", []):
                if isinstance(crumb, dict) and "data" in crumb:
                    crumb["data"] = scrub_sensitive_dict(crumb["data"])

    except Exception as exc:
        logger.debug(f"Error during Sentry event sanitization: {exc}")

    return event


def before_breadcrumb_handler(crumb: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Scrub sensitive data from breadcrumbs as they are collected."""
    try:
        if isinstance(crumb.get("data"), dict):
            crumb["data"] = scrub_sensitive_dict(crumb["data"])
    except Exception:
        pass
    return crumb


def init_sentry(process_name: str = "api") -> bool:
    """Initialize Sentry error tracking if SENTRY_DSN is configured.

    Safe failure behavior:
    - If SENTRY_DSN is None or empty, returns False and allows process to start normally.
    - If initialization fails, logs a warning and returns False without raising exceptions.
    - Captures zero request bodies by default.
    - Sets process tag ('api' or 'scheduler') for clear telemetry attribution.
    """
    dsn = (settings.SENTRY_DSN or "").strip()
    if not dsn:
        logger.info(
            f"Sentry error tracking is disabled for '{process_name}' (SENTRY_DSN not configured)."
        )
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        environment = settings.SENTRY_ENVIRONMENT or settings.APP_ENV
        release = settings.SENTRY_RELEASE or f"{settings.APP_NAME}@{settings.APP_VERSION}"

        sentry_logging = LoggingIntegration(
            level=None,  # Do not attach logging handler automatically; Nexus logging handles this
            event_level=None,
        )

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            server_name=f"nexus-{process_name}",
            send_default_pii=False,
            request_bodies="never",
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            before_send=before_send_handler,
            before_breadcrumb=before_breadcrumb_handler,
            integrations=[sentry_logging],
        )

        # Set attribution tag
        sentry_sdk.set_tag("process", process_name)
        sentry_sdk.set_tag("app_version", settings.APP_VERSION)

        logger.info(
            f"Sentry error tracking initialized successfully for '{process_name}' "
            f"[env={environment}, release={release}, sample_rate={settings.SENTRY_TRACES_SAMPLE_RATE}]."
        )
        return True

    except Exception as exc:
        logger.warning(
            f"Failed to initialize Sentry error tracking for '{process_name}': {exc}. "
            "Process startup continuing safely without external error tracking."
        )
        return False
