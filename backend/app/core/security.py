"""Security dependencies and authentication boundaries for NEXUS."""

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str | None:
    """
    Validate incoming request API key when API_KEY_ENABLED is True.
    
    If API_KEY_ENABLED is False (default for development/testing), requests
    are allowed unconditionally without credentials.
    """
    if not settings.API_KEY_ENABLED:
        return None

    if not settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API Key authentication is enabled on the server but no valid key is configured.",
        )

    if not api_key or api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key
