"""Read/write observer for Omada Stage 1 endpoints.

Every call is defensive: any failure (network, non-2xx, JSON decode) is
captured to omada-simulator/output/omada_audit.log and the method returns
None. Surfacing bugs is the point of the simulator, so we never raise.

No auth header is sent. The simulator only ever runs against a local
Omada whose ``clerk_auth`` feature flag is disabled — the API resolves
the caller to the first admin user without checking any token.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
AUDIT_LOG_PATH = PACKAGE_ROOT / "output" / "omada_audit.log"
REQUEST_TIMEOUT = 30.0


class OmadaObserver:
    def __init__(
        self,
        omada_url: str,
        *,
        audit_log_dir: Optional[Path] = None,
    ) -> None:
        self._base_url = omada_url.rstrip("/")
        self._client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        # Set by resolve_team_id() so endpoints that need team_id (e.g. the
        # retro generate query param) don't have to thread it through every call.
        self.team_id: Optional[str] = None
        # Per-team audit log dir (M6); falls back to module-level shared path
        # so stage-1 callers continue to write to output/omada_audit.log.
        if audit_log_dir is not None:
            self._audit_log_path = audit_log_dir / "omada_audit.log"
        else:
            self._audit_log_path = AUDIT_LOG_PATH

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OmadaObserver":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _log(self, method: str, path: str, status: str, preview: str) -> None:
        self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        safe_preview = (preview or "").replace("\n", " ").replace("\r", " ")[:200]
        line = f"{ts} | {method} | {path} | {status} | {safe_preview}\n"
        try:
            with self._audit_log_path.open("a") as f:
                f.write(line)
        except OSError:
            # Logging itself must never break the caller.
            pass

    def _request(
        self,
        method: str,
        path: str,
        timeout: float = REQUEST_TIMEOUT,
        **kwargs: Any,
    ) -> Optional[dict]:
        url = f"{self._base_url}{path}"
        try:
            response = self._client.request(method, url, timeout=timeout, **kwargs)
        except Exception as e:  # httpx.HTTPError and anything else
            self._log(method, path, "ERR", repr(e))
            return None

        body_text = response.text or ""
        if response.status_code >= 400:
            self._log(method, path, str(response.status_code), body_text)
            return None

        if not body_text.strip():
            self._log(method, path, str(response.status_code), "")
            return {}

        try:
            data = response.json()
        except Exception as e:
            self._log(method, path, f"{response.status_code}/JSONERR", repr(e))
            return None

        self._log(method, path, str(response.status_code), body_text)
        if not isinstance(data, dict):
            # Wrap list/scalar payloads so the return type stays dict | None.
            return {"data": data}
        return data

    def resolve_team_id(self) -> Optional[str]:
        """Resolve the caller's active Omada team id.

        /api/me only returns {"user_id": ...}, so we confirm auth there and
        then call GET /api/teams (which lists the teams accessible to the
        caller in camelCase: teamId / teamName / isPrimary). We prefer the
        primary team, otherwise the first team returned.
        """
        me = self._request("GET", "/api/me")
        if not me or not me.get("user_id"):
            return None

        teams_resp = self._request("GET", "/api/teams")
        if not teams_resp:
            return None

        teams = teams_resp.get("teams") or teams_resp.get("data") or []
        if not teams:
            return None

        for t in teams:
            if t.get("isPrimary") or t.get("is_primary"):
                tid = t.get("teamId") or t.get("team_id")
                if tid:
                    self.team_id = str(tid)
                    return self.team_id

        first = teams[0]
        tid = first.get("teamId") or first.get("team_id")
        if not tid:
            return None
        self.team_id = str(tid)
        return self.team_id

    def trigger_sync(self, team_id: str) -> Optional[dict]:
        return self._request(
            "POST",
            "/api/integrations/jira/sync",
            params={"team_id": team_id},
        )

    def switch_board(
        self,
        board_id: int,
        project_key: str,
        team_id: Optional[str] = None,
    ) -> bool:
        """Point Omada at a new Jira board/project without re-running OAuth.

        Called by `run_setup` after the simulator creates a fresh SIM project,
        so the existing connection credentials are reused and the user doesn't
        have to manually disconnect/reconnect in the UI. Returns True on success.

        When ``team_id`` is provided (M5+), the API switches the board for
        that specific team. When omitted, the API falls back to the org's
        primary team — preserving stage-1 behaviour.
        """
        payload: dict[str, Any] = {"board_id": board_id, "project_key": project_key}
        if team_id is not None:
            payload["team_id"] = team_id
        resp = self._request(
            "PUT",
            "/api/integrations/jira/board",
            json=payload,
        )
        return resp is not None

    def create_team(
        self,
        name: str,
        developers: Optional[list[dict]] = None,
    ) -> Optional[dict]:
        """POST /api/teams to create a per-team Omada team (M5).

        ``developers`` is a list of ``{"name": str, "role": str | None}``
        dicts — matches the frozen contract in plan §6.

        Returns the response dict on success (with ``teamId``, ``isNew``,
        and a ``developers`` list of ``{developerId, name}``). Returns
        ``None`` on any failure — most notably a 403 when the apps/api
        feature flag isn't enabled (production), or a 404 when the
        endpoint doesn't exist yet (callers should treat both as "fall
        back to the org's primary team", matching the M2-M4 path).
        """
        body = {
            "name": name,
            "developers": developers or [],
        }
        return self._request("POST", "/api/teams", json=body)

    def seed_tickets(
        self,
        team_id: str,
        tickets: list[dict],
    ) -> Optional[dict]:
        """POST /api/teams/{team_id}/seed-tickets — bulk-insert backlog
        Ticket rows directly, bypassing Jira sync.

        Used when the Jira OAuth connection's access token lacks the
        granular JQL scope (``read:jql:jira``) so ``sync_jira_team``
        401s on ``/search/jql`` — or simply when no Celery worker is
        running. Without this, a fresh per-team Omada team has no
        candidate pool and ``/api/sprint-brain/plan`` returns 422.

        ``tickets`` is a list of dicts with at minimum ``jira_issue_key``
        and ``title``; ``story_points``, ``ticket_type``, ``labels``
        are optional.

        Returns the response dict on success (``{"created": N,
        "updated": M}``). Returns None on failure (403 when the feature
        flag is off, 404 when the team doesn't exist, network errors).
        """
        body = {"tickets": tickets}
        return self._request("POST", f"/api/teams/{team_id}/seed-tickets", json=body)

    def get_sync_status(self) -> Optional[dict]:
        """Return the current Jira-integration status dict (or None on failure).

        Used as a "did the last sync finish?" probe via the ``last_synced_at``
        timestamp. Endpoint shape: ``{connected, cloud_url, last_synced_at}``.
        """
        return self._request("GET", "/api/integrations/jira/status")

    def wait_for_sync(
        self,
        *,
        before: Optional[str] = None,
        timeout: float = 60.0,
        interval: float = 2.0,
    ) -> bool:
        """Poll the Jira-integration status until ``last_synced_at`` advances.

        ``before`` is the ``last_synced_at`` value captured immediately before
        ``trigger_sync`` was called (``None`` if the org had never synced). We
        consider the sync "completed" when the endpoint reports a newer value.

        Returns True if completion was observed, False on timeout. Callers
        should fall back to a fixed sleep when this returns False.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.get_sync_status()
            if status:
                last = status.get("last_synced_at")
                if last and (before is None or last > before):
                    return True
            time.sleep(interval)
        return False

    def generate_sprint_plan(
        self,
        team_id: str,
        sprint_length_days: int = 14,
        sprint_start_date: Optional[str] = None,
    ) -> Optional[dict]:
        body: dict[str, Any] = {
            "team_id": team_id,
            "sprint_length_days": sprint_length_days,
        }
        if sprint_start_date is not None:
            body["sprint_start_date"] = sprint_start_date
        return self._request(
            "POST", "/api/sprint-brain/plan", json=body, timeout=120.0
        )

    def push_plan_to_jira(
        self, team_id: str, sprint_name: str, plan: dict, sprint_length_days: int = 14
    ) -> Optional[dict]:
        from datetime import date, timedelta
        sprint_start_str = plan.get("sprint_start") or date.today().isoformat()
        sprint_start = date.fromisoformat(sprint_start_str)
        sprint_end = sprint_start + timedelta(days=sprint_length_days)
        assignments = [
            {"ticketId": a["ticket_id"], "developerId": a["developer_id"]}
            for a in plan.get("assignments", [])
        ]
        body = {
            "teamId": team_id,
            "sprintName": sprint_name,
            "sprintStartDate": sprint_start_str,
            "sprintEndDate": sprint_end.isoformat(),
            "assignments": assignments,
        }
        return self._request("POST", "/api/sprint-brain/push-to-jira", json=body)

    def get_health_score(self, team_id: str) -> Optional[dict]:
        return self._request("GET", f"/api/teams/{team_id}/velocity")

    def get_capacity(self, team_id: str) -> Optional[dict]:
        return self._request("GET", f"/api/teams/{team_id}/capacity")

    def get_dependency_radar(self, team_id: str) -> Optional[dict]:
        return self._request("GET", f"/api/dependency-radar/team/{team_id}")

    def get_omada_sprint_id(self, jira_sprint_id: int) -> Optional[str]:
        """Look up an Omada sprint UUID by Jira sprint ID.

        The simulator only knows the integer Jira sprint id returned by
        ``JiraDriver.create_sprint``, but every Omada-side endpoint that
        operates on sprints (retro, etc.) keys on the Omada sprint UUID.
        We resolve the join via ``GET /api/sprints/completed``, which now
        exposes ``jiraSprintId`` for exactly this reason. Returns the
        Omada UUID (string) or None if not found.
        """
        resp = self._request("GET", "/api/sprints/completed")
        if not resp:
            self._log("LOOKUP", "/api/sprints/completed", "MISS",
                      f"no response for jira_sprint_id={jira_sprint_id}")
            return None

        sprints = resp.get("sprints") or resp.get("data") or []
        target = str(jira_sprint_id)
        for s in sprints:
            # camelCase from the API; tolerate snake_case too.
            jsid = s.get("jiraSprintId") or s.get("jira_sprint_id")
            if jsid is not None and str(jsid) == target:
                omada_id = s.get("id")
                if omada_id:
                    return str(omada_id)

        self._log(
            "LOOKUP",
            "/api/sprints/completed",
            "MISS",
            f"jira_sprint_id={jira_sprint_id} not found in {len(sprints)} sprints",
        )
        return None

    def get_retro(self, jira_sprint_id: int) -> Optional[dict]:
        """Generate (POST) and then fetch (GET) the retro for a Jira sprint.

        Accepts the Jira sprint id (integer) the simulator already has, looks
        up the corresponding Omada sprint UUID, then:
          1. POSTs /api/retro/generate/{omada_uuid}?team_id=...
          2. GETs  /api/retro/{omada_uuid}

        Returns the POST payload (which is the full retro body) on success.
        Falls back to the GET payload if POST returns nothing (e.g. retro
        was already generated and POST short-circuited). Returns None if
        we can't resolve the Omada sprint id at all.
        """
        omada_uuid = self.get_omada_sprint_id(jira_sprint_id)
        if not omada_uuid:
            self._log(
                "WARN",
                "get_retro",
                "SKIP",
                f"no Omada sprint UUID for jira_sprint_id={jira_sprint_id}",
            )
            return None

        params = {"team_id": self.team_id} if self.team_id else None
        generated = self._request(
            "POST",
            f"/api/retro/generate/{omada_uuid}",
            params=params,
        )
        fetched = self._request("GET", f"/api/retro/{omada_uuid}")
        return generated or fetched

    def get_features(self) -> Optional[dict]:
        return self._request("GET", "/api/features")
