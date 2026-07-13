import httpx
from urllib.parse import urlencode
from src.config import settings

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
# OAuth App (classic) scopes. `repo` is broad but is the only OAuth-App scope
# that grants private-repo read access; a later switch to a GitHub App gives
# per-repo grants (schema already carries nullable refresh/expiry for that).
GITHUB_SCOPES = "repo read:user user:email"


def get_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": GITHUB_SCOPES,
        "state": state,
    }
    return f"{GITHUB_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict:
    """Exchange the OAuth code for an access token.

    GitHub returns form-encoded by default; Accept: application/json switches
    it to JSON. Errors come back as 200s with an `error` key, so callers must
    check for `access_token` presence, not just the status code.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_redirect_uri,
            },
        )
        response.raise_for_status()
        return response.json()
