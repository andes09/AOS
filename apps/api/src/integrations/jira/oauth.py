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
    # --- Jira Platform (api/3) reads ---
    "read:project:jira",            # GET /project/search
    "read:project-category:jira",   # /project/search includes category data; without
                                    # this the endpoint returns 401 "scope does not match"
    "read:issue:jira",              # GET /issue/{key}
    "read:issue-details:jira",      # /issue/{key} with full field set + JQL search
    "read:issue-meta:jira",         # issue metadata returned on reads
    "read:issue-link:jira",         # issuelinks field
    "read:issue-type:jira",         # issuetype on issue payloads
    "read:status:jira",             # status on issue payloads
    "read:field:jira",              # customfield_* references
    "read:jql:jira",                # POST /search/jql
    # --- Jira users ---
    "read:user:jira",               # GET /users/search
    "read:application-role:jira",   # user object enrichment
    "read:group:jira",              # user object enrichment
    "read:avatar:jira",             # user avatars
    # --- Jira Platform writes ---
    "write:issue:jira",             # PUT /issue/{key} (fields + assignee)
    # --- Jira Software (Agile API) ---
    # Issue payloads returned by these endpoints are covered by the
    # platform-side read:issue:jira + read:issue-details:jira scopes above —
    # there's no equivalent jira-software variant in Atlassian's catalog.
    "read:board-scope:jira-software",      # GET /board, /board/{id}/backlog
    "read:sprint:jira-software",           # GET /board/{id}/sprint, /sprint/{id}/issue
    "write:sprint:jira-software",          # POST /sprint, POST /sprint/{id}/issue
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
