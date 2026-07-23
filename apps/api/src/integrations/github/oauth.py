import time
from urllib.parse import urlencode

import httpx
from jose import jwt

from src.config import settings
from src.integrations.github.client import GITHUB_API_BASE


def get_authorization_url(state: str) -> str:
    """Build the GitHub App installation URL. GitHub echoes `state` back on redirect."""
    params = {"state": state}
    return f"https://github.com/apps/{settings.github_app_slug}/installations/new?{urlencode(params)}"


def _generate_app_jwt() -> str:
    """Sign a short-lived JWT identifying the App itself (not an installation)."""
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": settings.github_app_id}
    return jwt.encode(payload, settings.github_app_private_key_pem, algorithm="RS256")


def _app_headers() -> dict:
    return {
        "Authorization": f"Bearer {_generate_app_jwt()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def get_installation(installation_id: str) -> dict:
    """Return the installation object (account identity, granted permissions)."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/app/installations/{installation_id}",
            headers=_app_headers(),
        )
        response.raise_for_status()
        return response.json()


async def get_installation_access_token(installation_id: str) -> dict:
    """Mint a fresh installation access token (~1h lifetime)."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens",
            headers=_app_headers(),
        )
        response.raise_for_status()
        return response.json()
