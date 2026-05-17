import httpx
from urllib.parse import urlencode
from src.config import settings

JIRA_AUTH_URL = "https://auth.atlassian.com/authorize"
JIRA_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
JIRA_SCOPES = " ".join([
    # ---- Platform: search + fields ----
    "read:jql:jira",
    "read:field:jira",

    # ---- Platform: issues (read) ----
    "read:issue:jira",
    "read:issue-details:jira",
    "read:issue-meta:jira",
    "read:issue-link:jira",
    "read:issue-type:jira",
    "read:issue-type-scheme:jira",
    "read:issue-type-screen-scheme:jira",
    "read:label:jira",
    "read:status:jira",
    "read:priority:jira",
    "read:resolution:jira",
    "read:issue.changelog:jira",
    "read:issue.transition:jira",

    # ---- Platform: issues (write) ----
    "write:issue:jira",

    # ---- Platform: worklog + time tracking ----
    "read:issue-worklog:jira",
    "write:issue-worklog:jira",
    "read:issue.time-tracking:jira",
    "write:issue.time-tracking:jira",

    # ---- Platform: comments ----
    "read:comment:jira",
    "write:comment:jira",

    # ---- Platform: projects ----
    "read:project:jira",
    "read:project-category:jira",
    "read:project.component:jira",
    "read:project-version:jira",

    # ---- Platform: users ----
    "read:user:jira",
    "read:application-role:jira",
    "read:group:jira",
    "read:avatar:jira",
    "read:email-address:jira",

    # ---- Platform: webhooks ----
    "read:webhook:jira",
    "write:webhook:jira",

    # ---- Jira Software (Agile): boards ----
    "read:board-scope:jira-software",
    "write:board-scope:jira-software",

    # ---- Jira Software (Agile): sprints ----
    "read:sprint:jira-software",
    "write:sprint:jira-software",

    # ---- Jira Software (Agile): epics + issues ----
    "read:epic:jira-software",
    "write:epic:jira-software",
    "read:issue:jira-software",
    "write:issue:jira-software",

    # ---- OAuth: refresh-token rotation ----
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
