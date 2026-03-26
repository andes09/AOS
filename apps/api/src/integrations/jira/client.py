import httpx
from dataclasses import dataclass


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
        """Execute a JQL search with full pagination. Works with read:jira-work scope only."""
        issues = []
        start_at = 0
        while True:
            async with httpx.AsyncClient() as c:
                r = await c.post(
                    f"{self.base_url}/search",
                    headers=self._headers(),
                    json={"jql": jql, "startAt": start_at, "maxResults": 100, "fields": fields},
                )
                r.raise_for_status()
                data = r.json()
                batch = data.get("issues", [])
                issues.extend(batch)
                if start_at + len(batch) >= data.get("total", 0):
                    break
                start_at += len(batch)
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
