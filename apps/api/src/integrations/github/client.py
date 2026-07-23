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
