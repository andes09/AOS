import httpx
from dataclasses import dataclass


@dataclass
class JiraClient:
    cloud_id: str
    access_token: str

    @property
    def base_url(self) -> str:
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/api/3"

    @property
    def agile_base_url(self) -> str:
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/agile/1.0"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}

    async def get_projects(self) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self.base_url}/project/search",
                headers=self._headers(),
                params={"maxResults": 50, "orderBy": "name"},
            )
            r.raise_for_status()
            return r.json().get("values", [])

    async def get_boards(self) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self.agile_base_url}/board",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json().get("values", [])

    async def get_sprints(self, board_id: str) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self.agile_base_url}/board/{board_id}/sprint",
                headers=self._headers(),
                params={"state": "active,closed", "maxResults": 50},
            )
            r.raise_for_status()
            return r.json().get("values", [])

    async def get_sprint_issues(self, sprint_id: str) -> list[dict]:
        issues = []
        start_at = 0
        fields = (
            "summary,status,assignee,story_points,issuetype,labels,"
            "components,timespent,timeoriginalestimate,created,updated,resolutiondate"
        )
        while True:
            async with httpx.AsyncClient() as c:
                r = await c.get(
                    f"{self.agile_base_url}/sprint/{sprint_id}/issue",
                    headers=self._headers(),
                    params={"startAt": start_at, "maxResults": 100, "fields": fields},
                )
                r.raise_for_status()
                data = r.json()
                issues.extend(data.get("issues", []))
                if start_at + 100 >= data.get("total", 0):
                    break
                start_at += 100
        return issues

    async def get_users(self) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self.base_url}/users/search",
                headers=self._headers(),
                params={"maxResults": 200, "accountType": "atlassian"},
            )
            r.raise_for_status()
            return r.json()
