from dataclasses import dataclass
from datetime import datetime

import httpx

GITHUB_API_BASE = "https://api.github.com"


def _parse_gh_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


@dataclass
class GithubClient:
    access_token: str

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def create_repo(self, org: str, name: str, private: bool = True) -> dict:
        """Create a repo under `org` (an Organization the installation is on),
        initialized with a README so it isn't empty. The one write method on
        this otherwise read-only client.

        Only works for Organization installs: a personal-account installation
        token can't create repos (there's no installation permission that
        grants creating a new user-owned repo — that needs a user-to-server
        OAuth token). Callers must gate on connection.account_type first (see
        onboarding_v2.create_repo)."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GITHUB_API_BASE}/orgs/{org}/repos",
                headers=self._headers,
                json={"name": name, "private": private, "auto_init": True},
            )
            response.raise_for_status()
            return response.json()

    async def list_repos(self, page: int = 1, per_page: int = 30) -> list[dict]:
        """List repos the installation token can access."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/installation/repositories",
                headers=self._headers,
                params={"page": page, "per_page": per_page},
            )
            response.raise_for_status()
            return response.json()["repositories"]

    async def list_commits(
        self,
        owner: str,
        repo: str,
        since: datetime | None = None,
        branch: str | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> list[dict]:
        """List commits, for the reconciliation sweep. `/commits` natively
        supports `since` server-side, unlike `/pulls` (see `list_pull_requests`)."""
        params: dict = {"page": page, "per_page": per_page}
        if since is not None:
            params["since"] = since.isoformat() + "Z"
        if branch is not None:
            params["sha"] = branch
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits",
                headers=self._headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        since: datetime | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> list[dict]:
        """List pull requests, for the reconciliation sweep.

        GitHub's `/pulls` endpoint has no server-side `since` filter (unlike
        `/commits`), so we sort by `updated` descending and filter client-side
        — good enough for a low-frequency reconciliation sweep over a bounded
        page of recently-updated PRs, not meant for deep historical backfill.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
                headers=self._headers,
                params={
                    "state": state,
                    "sort": "updated",
                    "direction": "desc",
                    "page": page,
                    "per_page": per_page,
                },
            )
            response.raise_for_status()
            prs = response.json()
        if since is not None:
            prs = [pr for pr in prs if (_parse_gh_datetime(pr.get("updated_at")) or since) > since]
        return prs
