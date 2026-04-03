import logging

import httpx
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class JiraClient:
    cloud_id: str
    access_token: str

    @property
    def base_url(self) -> str:
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/api/3"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}

    async def search_issues(self, jql: str, fields: list[str]) -> list[dict]:
        """Execute a JQL search with full pagination using the /search/jql endpoint.

        Uses cursor-based pagination (nextPageToken) required by the new API.
        Works with read:jira-work scope only.
        """
        issues = []
        next_page_token: str | None = None
        while True:
            body: dict = {"jql": jql, "maxResults": 100, "fields": fields}
            if next_page_token:
                body["nextPageToken"] = next_page_token
            async with httpx.AsyncClient() as c:
                r = await c.post(
                    f"{self.base_url}/search/jql",
                    headers=self._headers(),
                    json=body,
                )
                if not r.is_success:
                    logger.error(
                        "Jira search/jql %s — body: %s",
                        r.status_code,
                        r.text[:500],
                    )
                r.raise_for_status()
                data = r.json()
                batch = data.get("issues", [])
                issues.extend(batch)
                next_page_token = data.get("nextPageToken")
                if not next_page_token or not batch:
                    break
        return issues

    async def get_projects(self) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self.base_url}/project/search",
                headers=self._headers(),
                params={"maxResults": 50, "orderBy": "name"},
            )
            r.raise_for_status()
            return r.json().get("values", [])

    async def get_sprints(self, board_id: str = None) -> list[dict]:
        """
        Extract unique sprint metadata from issue sprint fields.
        Uses JQL + customfield_10020 — no Jira Software scope required.
        board_id is accepted but ignored; kept for call-site compatibility.
        """
        issues = await self.search_issues(
            jql="sprint in openSprints() or sprint in closedSprints()",
            fields=["customfield_10020"],
        )
        seen: set[int] = set()
        sprints: list[dict] = []
        for issue in issues:
            sprint_field = issue.get("fields", {}).get("customfield_10020") or []
            if isinstance(sprint_field, dict):
                sprint_field = [sprint_field]
            for sprint in sprint_field:
                sid = sprint.get("id")
                if sid and sid not in seen:
                    seen.add(sid)
                    sprints.append(sprint)
        return sprints

    async def get_sprint_issues(self, sprint_id: str) -> list[dict]:
        """
        Fetch all issues belonging to a sprint using JQL.
        No Jira Software scope required.
        """
        fields = [
            "summary", "status", "assignee", "issuetype", "labels",
            "components", "timespent", "timeoriginalestimate", "created",
            "updated", "resolutiondate", "customfield_10016", "customfield_10028",
        ]
        return await self.search_issues(
            jql=f"sprint = {sprint_id} ORDER BY created ASC",
            fields=fields,
        )

    async def get_users(self) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self.base_url}/users/search",
                headers=self._headers(),
                params={"maxResults": 200, "accountType": "atlassian"},
            )
            r.raise_for_status()
            return r.json()

    @property
    def agile_base_url(self) -> str:
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/agile/1.0"

    async def create_sprint(self, board_id: str, name: str, start_date: str, end_date: str) -> dict:
        """POST /agile/1.0/sprint — returns sprint dict with 'id' and 'self' URL."""
        async with httpx.AsyncClient() as c:
            r = await c.post(
                f"{self.agile_base_url}/sprint",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"originBoardId": board_id, "name": name, "startDate": start_date, "endDate": end_date},
            )
            r.raise_for_status()
            return r.json()

    async def move_issues_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> None:
        """POST /agile/1.0/sprint/{id}/issue"""
        async with httpx.AsyncClient() as c:
            r = await c.post(
                f"{self.agile_base_url}/sprint/{sprint_id}/issue",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"issues": issue_keys},
            )
            r.raise_for_status()

    async def assign_issue(self, issue_key: str, jira_account_id: str) -> None:
        """PUT /rest/api/3/issue/{key}/assignee"""
        async with httpx.AsyncClient() as c:
            r = await c.put(
                f"{self.base_url}/issue/{issue_key}/assignee",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"accountId": jira_account_id},
            )
            r.raise_for_status()
