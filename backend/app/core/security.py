"""Security dependencies and authentication boundaries for NEXUS."""

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def verify_api_key(
    api_key: str | None = Security(api_key_header),
    bearer_creds: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> str | None:
    """
    Validate incoming request credentials when API_KEY_ENABLED is True.
    Supports either 'X-API-Key: <key>' or 'Authorization: Bearer <key>'.

    If API_KEY_ENABLED is False (default for development/testing), requests
    are allowed unconditionally without credentials.
    """
    if not settings.API_KEY_ENABLED:
        return None

    token = api_key or (bearer_creds.credentials if bearer_creds else None)

    if not settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API Key authentication is enabled on the server but no valid key is configured.",
        )

    if not token or token != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authentication credentials. Provide a valid 'X-API-Key' or 'Authorization: Bearer <key>'.",
            headers={"WWW-Authenticate": "Bearer, ApiKey"},
        )

    return token
