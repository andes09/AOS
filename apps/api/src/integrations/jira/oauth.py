import httpx
from urllib.parse import urlencode
from src.config import settings

JIRA_AUTH_URL = "https://auth.atlassian.com/authorize"
JIRA_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
# Granular OAuth 2.0 scopes. Atlassian unified-Jira enforces granular scopes
# for /rest/agile/1.0 — classic read:jira-work returns
# {"code":401,"message":"Unauthorized; scope does not match"} on board calls
# even though docs claim coverage. Mixing classic and granular on the same
# OAuth app is rejected by the dev console, so we go fully granular.
JIRA_SCOPES = " ".join([
    # --- Jira Platform: project metadata ---
    # /project/search was returning FAILURE_CLIENT_SCOPE_CHECK with only
    # read:project:jira + read:project-category:jira granted, so we add
    # every plausible project-* scope to cover whatever undocumented
    # requirement Atlassian's edge is enforcing.
    "read:project:jira",
    "read:project-category:jira",
    "read:project-version:jira",
    "read:project-role:jira",
    "read:project.property:jira",
    "read:project.component:jira",
    "read:project.feature:jira",
    # --- Jira Platform: issue reads ---
    "read:issue:jira",
    "read:issue-details:jira",
    "read:issue-meta:jira",
    "read:issue-link:jira",
    "read:issue-type:jira",
    "read:issue.changelog:jira",
    "read:issue.transition:jira",
    "read:issue.property:jira",
    "read:issue-worklog:jira",
    "read:status:jira",
    "read:field:jira",
    "read:jql:jira",
    # --- Jira users + identity ---
    "read:user:jira",
    "read:application-role:jira",
    "read:group:jira",
    "read:avatar:jira",
    "read:permission:jira",
    # --- Jira Platform writes ---
    "write:issue:jira",
    # --- Jira Software (Agile API) ---
    "read:board-scope:jira-software",
    "read:sprint:jira-software",
    "read:epic:jira-software",
    "write:sprint:jira-software",
    # --- Refresh ---
    "offline_access",
])
JIRA_ACCESSIBLE_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"


def get_authorization_url(state: str) -> str:
    params = {
        "audience": "api.atlassian.com",
        "client_id": settings.jira_client_id,
        "scope": JIRA_SCOPES,
        "redirect_uri": settings.jira_redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    return f"{JIRA_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            JIRA_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.jira_client_id,
                "client_secret": settings.jira_client_secret,
                "code": code,
                "redirect_uri": settings.jira_redirect_uri,
            },
        )
        response.raise_for_status()
        return response.json()


async def get_accessible_resources(access_token: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            JIRA_ACCESSIBLE_RESOURCES_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()


async def refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            JIRA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.jira_client_id,
                "client_secret": settings.jira_client_secret,
                "refresh_token": refresh_token,
            },
        )
        response.raise_for_status()
        return response.json()
