"""Read/write observer for Omada Stage 1 endpoints.

Every call is defensive: any failure (network, non-2xx, JSON decode) is
captured to omada-simulator/output/omada_audit.log and the method returns
None. Surfacing bugs is the point of the simulator, so we never raise.

No auth header is sent. The simulator only ever runs against a local
Omada whose ``clerk_auth`` feature flag is disabled — the API resolves
the caller to the first admin user without checking any token.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
AUDIT_LOG_PATH = PACKAGE_ROOT / "output" / "omada_audit.log"
REQUEST_TIMEOUT = 30.0


class OmadaObserver:
    def __init__(self, omada_url: str) -> None:
        self._base_url = omada_url.rstrip("/")
        self._client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OmadaObserver":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _log(self, method: str, path: str, status: str, preview: str) -> None:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        safe_preview = (preview or "").replace("\n", " ").replace("\r", " ")[:200]
        line = f"{ts} | {method} | {path} | {status} | {safe_preview}\n"
        try:
            with AUDIT_LOG_PATH.open("a") as f:
                f.write(line)
        except OSError:
            # Logging itself must never break the caller.
            pass

    def _request(self, method: str, path: str, **kwargs: Any) -> Optional[dict]:
        url = f"{self._base_url}{path}"
        try:
            response = self._client.request(method, url, **kwargs)
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
                    return str(tid)

        first = teams[0]
        tid = first.get("teamId") or first.get("team_id")
        return str(tid) if tid else None

    def trigger_sync(self, team_id: str) -> Optional[dict]:
        return self._request(
            "POST",
            "/api/integrations/jira/sync",
            params={"team_id": team_id},
        )

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
        return self._request("POST", "/api/sprint-brain/plan", json=body)

    def push_plan_to_jira(
        self, team_id: str, sprint_name: str, plan: dict
    ) -> Optional[dict]:
        body = {
            "teamId": team_id,
            "sprintName": sprint_name,
            "plan": plan,
        }
        return self._request("POST", "/api/sprint-brain/push-to-jira", json=body)

    def get_health_score(self, team_id: str) -> Optional[dict]:
        return self._request("GET", f"/api/teams/{team_id}/velocity")

    def get_capacity(self, team_id: str) -> Optional[dict]:
        return self._request("GET", f"/api/teams/{team_id}/capacity")

    def get_dependency_radar(self, team_id: str) -> Optional[dict]:
        return self._request("GET", f"/api/dependency-radar/team/{team_id}")

    def get_retro(self, sprint_id: str) -> Optional[dict]:
        return self._request("GET", f"/api/retro/{sprint_id}")

    def generate_retro(self, sprint_id: str) -> Optional[dict]:
        return self._request("POST", f"/api/retro/generate/{sprint_id}")

    def get_features(self) -> Optional[dict]:
        return self._request("GET", "/api/features")
