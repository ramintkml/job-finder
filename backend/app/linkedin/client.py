"""LinkedIn OAuth client (Sign In with LinkedIn — OpenID Connect)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
SCOPES = "openid profile email"


class LinkedInApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def build_authorize_url(*, state: str) -> str:
    if not settings.linkedin_client_id:
        raise LinkedInApiError("LINKEDIN_CLIENT_ID is not configured in backend/.env")

    params: dict[str, str] = {
        "response_type": "code",
        "client_id": settings.linkedin_client_id,
        "redirect_uri": settings.linkedin_redirect_uri,
        "state": state,
        "scope": SCOPES,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    if not settings.linkedin_client_id or not settings.linkedin_client_secret:
        raise LinkedInApiError(
            "LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in backend/.env"
        )

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.linkedin_client_id,
        "client_secret": settings.linkedin_client_secret,
        "redirect_uri": settings.linkedin_redirect_uri,
    }
    return await _token_request(data)


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    if not settings.linkedin_client_id or not settings.linkedin_client_secret:
        raise LinkedInApiError("LinkedIn client credentials are not configured")

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.linkedin_client_id,
        "client_secret": settings.linkedin_client_secret,
    }
    return await _token_request(data)


async def _token_request(data: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text[:500]}

    if isinstance(payload, dict) and payload.get("error"):
        description = payload.get("error_description") or payload["error"]
        raise LinkedInApiError(
            f"OAuth error: {description}",
            status_code=response.status_code,
            body=payload,
        )

    if response.status_code != 200:
        detail = response.text[:500]
        raise LinkedInApiError(
            f"Token request failed ({response.status_code}): {detail}",
            status_code=response.status_code,
            body=detail,
        )

    if "access_token" not in payload:
        raise LinkedInApiError(f"Token response missing access_token: {payload}")
    return payload


async def get_userinfo(access_token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(USERINFO_URL, headers=headers)

    if response.status_code != 200:
        raise LinkedInApiError(
            f"Userinfo request failed ({response.status_code}): {response.text[:500]}",
            status_code=response.status_code,
            body=response.text,
        )

    payload = response.json()
    if not isinstance(payload, dict):
        raise LinkedInApiError("Unexpected userinfo response")
    return payload
