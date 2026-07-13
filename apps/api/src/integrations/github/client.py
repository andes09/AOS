from dataclasses import dataclass

import httpx

GITHUB_API_BASE = "https://api.github.com"


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

    async def get_user(self) -> dict:
        """Return the authenticated user (id, login, avatar_url, ...)."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{GITHUB_API_BASE}/user", headers=self._headers)
            response.raise_for_status()
            return response.json()

    async def list_repos(self, page: int = 1, per_page: int = 30) -> list[dict]:
        """List repos the token can access, most recently pushed first."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/user/repos",
                headers=self._headers,
                params={"page": page, "per_page": per_page, "sort": "pushed"},
            )
            response.raise_for_status()
            return response.json()
