"""Atlassian Jira Cloud REST API driver with auditing and retry/backoff."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PACKAGE_ROOT / "output"
AUDIT_LOG_PATH = OUTPUT_DIR / "jira_audit.log"

MIN_REQUEST_INTERVAL = 0.1  # 10 req/sec ceiling
MAX_RETRIES = 3
BACKOFF_SECONDS = (1.0, 2.0, 4.0)

logger = logging.getLogger(__name__)


class JiraDriverError(Exception):
    """Raised on non-recoverable Jira API failures."""


class JiraDriver:
    def __init__(self, jira_url: str, email: str, token: str) -> None:
        self.base_url = jira_url.rstrip("/")
        self._auth = httpx.BasicAuth(email, token)
        self._client = httpx.Client(
            auth=self._auth,
            timeout=httpx.Timeout(30.0),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        self._last_request_time: float = 0.0
        self._account_id: str | None = None
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def _audit(self, method: str, path: str, status: Any, duration_ms: int) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        line = f"{ts} | {method} | {path} | {status} | {duration_ms}ms\n"
        with AUDIT_LOG_PATH.open("a") as f:
            f.write(line)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            self._throttle()
            start = time.monotonic()
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as e:
                self._last_request_time = time.monotonic()
                duration_ms = int((time.monotonic() - start) * 1000)
                self._audit(method, path, f"ERR:{type(e).__name__}", duration_ms)
                last_exc = e
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_SECONDS[attempt])
                    continue
                raise JiraDriverError(
                    f"Network error after {MAX_RETRIES} retries: {method} {path}: {e}"
                ) from e

            self._last_request_time = time.monotonic()
            duration_ms = int((time.monotonic() - start) * 1000)
            self._audit(method, path, response.status_code, duration_ms)

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_SECONDS[attempt])
                    continue
                raise JiraDriverError(
                    f"Retries exhausted: {method} {path} → "
                    f"{response.status_code}: {response.text[:200]}"
                )

            if 400 <= response.status_code < 500 and response.status_code != 404:
                raise JiraDriverError(
                    f"Client error: {method} {path} → "
                    f"{response.status_code}: {response.text[:200]}"
                )

            return response

        # Should be unreachable; keep mypy/readers happy.
        raise JiraDriverError(f"Unexpected retry loop exit: {last_exc}")

    def _current_account_id(self) -> str:
        if self._account_id is None:
            resp = self._request("GET", "/rest/api/3/myself")
            self._account_id = resp.json()["accountId"]
        return self._account_id

    def get_or_create_project(self, key: str, name: str) -> dict:
        resp = self._request("GET", f"/rest/api/3/project/{key}")
        if resp.status_code == 200:
            return resp.json()

        body = {
            "key": key,
            "name": name,
            "projectTypeKey": "software",
            "projectTemplateKey": (
                "com.pyxis.greenhopper.jira.gh-simplified-agility-scrum"
            ),
            "leadAccountId": self._current_account_id(),
        }
        create = self._request("POST", "/rest/api/3/project", json=body)
        return create.json()

    def get_board_id(self, project_key: str) -> int:
        resp = self._request(
            "GET",
            f"/rest/agile/1.0/board?projectKeyOrId={project_key}",
        )
        data = resp.json()
        values = data.get("values") or []
        if not values:
            raise JiraDriverError(
                f"No board found for project {project_key}. "
                f"Scrum board may still be provisioning."
            )
        return int(values[0]["id"])

    def create_ticket(
        self,
        project_key: str,
        summary: str,
        issue_type: str,
        story_points: int,
        labels: list[str] | None = None,
        description: str = "",
    ) -> str:
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
            "customfield_10016": story_points,
            "labels": labels or [],
        }
        if description:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            }
        resp = self._request("POST", "/rest/api/3/issue", json={"fields": fields})
        return resp.json()["key"]

    def create_sprint(
        self, board_id: int, name: str, start_date: str, end_date: str
    ) -> int:
        body = {
            "originBoardId": board_id,
            "name": name,
            "startDate": start_date,
            "endDate": end_date,
        }
        create = self._request("POST", "/rest/agile/1.0/sprint", json=body)
        sprint_id = int(create.json()["id"])
        # Activate immediately so the sprint counts as in-progress.
        self._request(
            "PUT",
            f"/rest/agile/1.0/sprint/{sprint_id}",
            json={"state": "active"},
        )
        return sprint_id

    def add_issues_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> None:
        for i in range(0, len(issue_keys), 50):
            chunk = issue_keys[i : i + 50]
            self._request(
                "POST",
                f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                json={"issues": chunk},
            )

    def transition_issue(self, issue_key: str, target_status: str) -> None:
        resp = self._request("GET", f"/rest/api/3/issue/{issue_key}/transitions")
        transitions = resp.json().get("transitions", [])
        target_lower = target_status.lower()
        match = next(
            (
                t
                for t in transitions
                if t.get("to", {}).get("name", "").lower() == target_lower
            ),
            None,
        )
        if match is None:
            logger.warning(
                "No transition to '%s' found for %s", target_status, issue_key
            )
            self._audit(
                "POST",
                f"/rest/api/3/issue/{issue_key}/transitions",
                "NO_TRANSITION",
                0,
            )
            return
        self._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/transitions",
            json={"transition": {"id": match["id"]}},
        )

    def close_sprint(self, sprint_id: int) -> None:
        self._request(
            "PUT",
            f"/rest/agile/1.0/sprint/{sprint_id}",
            json={"state": "closed"},
        )

    def create_issue_link(self, outward_key: str, inward_key: str) -> None:
        try:
            self._request(
                "POST",
                "/rest/api/3/issueLink",
                json={
                    "type": {"name": "Blocks"},
                    "outwardIssue": {"key": outward_key},
                    "inwardIssue": {"key": inward_key},
                },
            )
        except Exception as e:
            logger.warning(
                "Failed to link %s -> %s: %s", outward_key, inward_key, e
            )

    def delete_project(self, project_key: str) -> None:
        if not project_key.startswith("SIM"):
            raise JiraDriverError("Refusing to delete non-SIM project")
        self._request("DELETE", f"/rest/api/3/project/{project_key}")

    def list_projects(self) -> list[dict]:
        resp = self._request("GET", "/rest/api/3/project")
        return [
            {"key": p["key"], "name": p["name"], "id": p["id"]}
            for p in resp.json()
        ]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "JiraDriver":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
