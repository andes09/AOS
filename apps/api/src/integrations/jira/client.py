import logging

import httpx
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _plain_text_to_adf(text: str) -> dict:
    """Wrap a plain-text string in the minimal Atlassian Document Format envelope.

    Jira's REST v3 ``description`` field requires ADF rather than raw text.
    Initiative B v1 emits plain-text revisions only; richer formatting (bullets,
    headings, links) is deferred to v2. This helper builds the smallest valid
    ADF doc containing a single paragraph with the given text.
    """
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


@dataclass
class JiraClient:
    cloud_id: str
    access_token: str

    def __post_init__(self):
        # Shared across all requests in this client's lifetime — avoids
        # a TCP+TLS handshake on every paginated call.
        self._http = httpx.AsyncClient(timeout=30.0)

    @property
    def base_url(self) -> str:
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/api/3"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}

    async def search_issues(self, jql: str, fields: list[str]) -> list[dict]:
        """Execute a JQL search with full pagination using the /search/jql endpoint.

        Uses cursor-based pagination (nextPageToken) required by the new API.
        Requires the granular read:jql:jira + read:issue-details:jira scopes.
        """
        issues = []
        next_page_token: str | None = None
        while True:
            body: dict = {"jql": jql, "maxResults": 100, "fields": fields}
            if next_page_token:
                body["nextPageToken"] = next_page_token
            r = await self._http.post(
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
        r = await self._http.get(
            f"{self.base_url}/project/search",
            headers=self._headers(),
            params={"maxResults": 50, "orderBy": "name"},
        )
        r.raise_for_status()
        return r.json().get("values", [])

    async def get_boards(self) -> list[dict]:
        """GET /agile/1.0/board — returns all boards visible to the token.

        Uses the Agile API (read:board-scope:jira-software) which is more
        reliable than the Platform API project/search for board selection.
        """
        boards = []
        start_at = 0
        while True:
            r = await self._http.get(
                f"{self.agile_base_url}/board",
                headers=self._headers(),
                params={"maxResults": 50, "startAt": start_at},
            )
            r.raise_for_status()
            data = r.json()
            batch = data.get("values", [])
            boards.extend(batch)
            if data.get("isLast", True) or not batch:
                break
            start_at += len(batch)
        return boards

    async def get_board_sprints(self, board_id: str) -> list[dict]:
        """GET /agile/1.0/board/{boardId}/sprint — all sprints for a board."""
        sprints = []
        start_at = 0
        while True:
            r = await self._http.get(
                f"{self.agile_base_url}/board/{board_id}/sprint",
                headers=self._headers(),
                params={"maxResults": 50, "startAt": start_at},
            )
            r.raise_for_status()
            data = r.json()
            batch = data.get("values", [])
            sprints.extend(batch)
            if data.get("isLast", True) or not batch:
                break
            start_at += len(batch)
        return sprints

    async def get_sprint_issues(self, sprint_id: str) -> list[dict]:
        """GET /agile/1.0/sprint/{sprintId}/issue — all issues in a sprint."""
        fields = [
            "summary", "status", "assignee", "issuetype", "labels",
            "components", "timespent", "timeoriginalestimate", "created",
            "updated", "resolutiondate", "customfield_10016", "customfield_10028",
        ]
        issues = []
        start_at = 0
        while True:
            r = await self._http.get(
                f"{self.agile_base_url}/sprint/{sprint_id}/issue",
                headers=self._headers(),
                params={"fields": ",".join(fields), "maxResults": 100, "startAt": start_at},
            )
            r.raise_for_status()
            data = r.json()
            batch = data.get("issues", [])
            issues.extend(batch)
            start_at += len(batch)
            if not batch or start_at >= data.get("total", 0):
                break
        return issues

    async def get_board_backlog(self, board_id: str, fields: list[str] | None = None) -> list[dict]:
        """GET /agile/1.0/board/{boardId}/backlog — issues not in any sprint."""
        if fields is None:
            fields = [
                "summary", "status", "assignee", "issuetype", "labels",
                "components", "timespent", "timeoriginalestimate", "created",
                "updated", "resolutiondate", "customfield_10016", "customfield_10028",
            ]
        issues = []
        start_at = 0
        while True:
            r = await self._http.get(
                f"{self.agile_base_url}/board/{board_id}/backlog",
                headers=self._headers(),
                params={"fields": ",".join(fields), "maxResults": 100, "startAt": start_at},
            )
            r.raise_for_status()
            data = r.json()
            batch = data.get("issues", [])
            issues.extend(batch)
            start_at += len(batch)
            if not batch or start_at >= data.get("total", 0):
                break
        return issues

    async def get_users(self) -> list[dict]:
        r = await self._http.get(
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
        r = await self._http.post(
            f"{self.agile_base_url}/sprint",
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"originBoardId": board_id, "name": name, "startDate": start_date, "endDate": end_date},
        )
        r.raise_for_status()
        return r.json()

    async def move_issues_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> None:
        """POST /agile/1.0/sprint/{id}/issue"""
        r = await self._http.post(
            f"{self.agile_base_url}/sprint/{sprint_id}/issue",
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"issues": issue_keys},
        )
        if not r.is_success:
            logger.error(
                "move_issues_to_sprint %s — keys=%s body: %s",
                r.status_code, issue_keys, r.text[:500],
            )
        r.raise_for_status()

    async def update_issue(self, issue_key: str, fields: dict) -> dict:
        """PUT /rest/api/3/issue/{issue_key} with body ``{"fields": fields}``.

        Accepts arbitrary Jira field keys — ``summary``, ``description``,
        ``customfield_xxx`` (story points / acceptance criteria),
        ``assignee={"accountId": ...}``, etc. Jira returns ``204 No Content``
        on success.

        If ``fields`` contains a ``description`` key whose value is a string,
        it is transparently wrapped in the minimal ADF envelope expected by
        the v3 API (see :func:`_plain_text_to_adf`). A dict value is forwarded
        unchanged so callers can supply pre-built ADF when needed.

        Returns the input ``fields`` dict (with any string ``description``
        replaced by its ADF form) on success. Raises ``httpx.HTTPStatusError``
        on any non-2xx response, mirroring :meth:`assign_issue`.
        """
        payload_fields = dict(fields)
        desc = payload_fields.get("description")
        if isinstance(desc, str):
            payload_fields["description"] = _plain_text_to_adf(desc)

        r = await self._http.put(
            f"{self.base_url}/issue/{issue_key}",
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"fields": payload_fields},
        )
        if not r.is_success:
            logger.error(
                "Jira update_issue %s — status=%s body=%s",
                issue_key, r.status_code, r.text[:500],
            )
        r.raise_for_status()
        return payload_fields

    async def assign_issue(self, issue_key: str, jira_account_id: str) -> None:
        """PUT /rest/api/3/issue/{key}/assignee"""
        r = await self._http.put(
            f"{self.base_url}/issue/{issue_key}/assignee",
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"accountId": jira_account_id},
        )
        r.raise_for_status()

    async def get_issue(self, issue_key: str) -> dict:
        """
        GET /rest/api/3/issue/{issue_key} with the fields needed for
        identifier-bootstrap scanning and Initiative B optimistic-concurrency.

        Returns the raw Jira issue payload:
            {"key": "PROJ-123",
             "fields": {"summary", "description",
                        "customfield_10014", "parent", "issuetype",
                        "updated"}}

        ``updated`` is Jira's ISO-8601 last-modified timestamp; callers use it
        as the ``fetched_updated_at`` value for stale-write detection on push
        (see :meth:`check_stale`).

        Raises ``HTTPException(404)`` when the issue is not found, mirroring
        :meth:`get_issue_links`.
        """
        from fastapi import HTTPException

        r = await self._http.get(
            f"{self.base_url}/issue/{issue_key}",
            headers=self._headers(),
            params={
                "fields": (
                    "description,customfield_10014,parent,summary,"
                    "issuetype,updated"
                )
            },
        )
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Issue {issue_key} not found in Jira")
        if not r.is_success:
            logger.error(
                "Jira get_issue %s — status=%s body=%s",
                issue_key, r.status_code, r.text[:500],
            )
        r.raise_for_status()
        return r.json()

    async def check_stale(self, issue_key: str, fetched_updated_at: str) -> bool:
        """Return ``True`` if Jira's ``fields.updated`` is newer than
        ``fetched_updated_at`` — i.e. the issue has been modified since we
        snapshotted it.

        Used by Initiative B's inline-refinement push path to detect that
        another writer (or a human editing directly in Jira) has touched the
        ticket between Scope Cop generating a ``suggested_revision`` and the
        user accepting it. If stale, the modal should warn before overwriting.

        Comparison strategy:
          * If both timestamps are ISO-8601 strings with the same shape
            (Jira's ``YYYY-MM-DDTHH:MM:SS.sss+ZZZZ``), lexicographic compare
            is correct.
          * Otherwise, fall back to ``datetime.fromisoformat`` parsing.

        Args:
            issue_key:          Jira issue key (e.g. "PROJ-123").
            fetched_updated_at: ISO-8601 timestamp snapshotted at fetch time.

        Returns:
            True if Jira's value is strictly newer; False if equal or older
            (or if ``fetched_updated_at`` is empty/None — treated as "fresh").
        """
        if not fetched_updated_at:
            return False

        issue = await self.get_issue(issue_key)
        jira_updated = (issue.get("fields") or {}).get("updated")
        if not jira_updated:
            # Jira didn't return an updated stamp — be conservative and treat
            # as not-stale rather than blocking the write.
            return False

        # Fast path: both strings, same format → lexicographic compare works.
        if isinstance(jira_updated, str) and isinstance(fetched_updated_at, str):
            try:
                return jira_updated > fetched_updated_at
            except TypeError:
                pass

        # Fallback: parse to datetime (handles mixed TZ formats).
        from datetime import datetime

        def _parse(s: str):
            # Jira uses +0000 (no colon) which fromisoformat <3.11 chokes on;
            # normalize to +00:00.
            if len(s) >= 5 and (s[-5] in ("+", "-")) and s[-3] != ":":
                s = s[:-2] + ":" + s[-2:]
            return datetime.fromisoformat(s)

        try:
            return _parse(jira_updated) > _parse(fetched_updated_at)
        except (ValueError, TypeError):
            # Can't parse — be conservative.
            return False

    async def get_issue_links(self, issue_key: str) -> list[dict]:
        """
        GET /rest/api/3/issue/{key}?fields=issuelinks,summary
        Returns list of { "type": str, "inwardIssue": dict|None, "outwardIssue": dict|None }
        Raises HTTPException(404) if issue not found.
        """
        from fastapi import HTTPException

        r = await self._http.get(
            f"{self.base_url}/issue/{issue_key}",
            headers=self._headers(),
            params={"fields": "issuelinks,summary"},
        )
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Issue {issue_key} not found in Jira")
        r.raise_for_status()
        data = r.json()

        raw_links = data.get("fields", {}).get("issuelinks", [])
        return [
            {
                "type": link.get("type", {}).get("name", ""),
                "inwardIssue": link.get("inwardIssue"),
                "outwardIssue": link.get("outwardIssue"),
            }
            for link in raw_links
        ]
