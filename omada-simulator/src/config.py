"""Environment-aware configuration loading and safety validation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import httpx
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
ENV_DIR = PACKAGE_ROOT / "config" / "environments"
TEAM_DIR = PACKAGE_ROOT / "config" / "teams"


class OmadaConfig(BaseModel):
    api_url: str


class JiraConfig(BaseModel):
    url: str
    project_key_prefix: str


class SafetyConfig(BaseModel):
    allow_production: bool = False
    required_url_substrings: list[str] = []
    block_url_substrings: list[str] = []
    max_real_users_in_org: int = 5
    require_simulated_org: bool = False
    refuse_with_message: Optional[str] = None


class EnvironmentConfig(BaseModel):
    name: str
    description: str
    omada: OmadaConfig
    jira: JiraConfig
    safety: SafetyConfig


class Secrets(BaseModel):
    jira_email: str
    jira_api_token: str
    omada_clerk_token: str


def load_environment(env_name: str) -> EnvironmentConfig:
    """Load config/environments/{env_name}.yaml as a validated EnvironmentConfig.

    Raises FileNotFoundError if the YAML file does not exist.
    Raises pydantic.ValidationError if the YAML is malformed or missing fields.
    """
    path = ENV_DIR / f"{env_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Environment config not found: {path}. "
            f"Available: {sorted(p.stem for p in ENV_DIR.glob('*.yaml'))}"
        )
    with path.open() as f:
        raw = yaml.safe_load(f)
    return EnvironmentConfig.model_validate(raw)


def load_secrets() -> Secrets:
    """Load .env from disk and return a validated Secrets object.

    Raises SystemExit with a clear message if any required secret is missing.
    """
    load_dotenv(PACKAGE_ROOT / ".env")
    missing = []
    jira_email = os.getenv("JIRA_EMAIL")
    jira_api_token = os.getenv("JIRA_API_TOKEN")
    omada_clerk_token = os.getenv("OMADA_CLERK_TOKEN")
    if not jira_email:
        missing.append("JIRA_EMAIL")
    if not jira_api_token:
        missing.append("JIRA_API_TOKEN")
    if not omada_clerk_token:
        missing.append("OMADA_CLERK_TOKEN")
    if missing:
        raise SystemExit(
            f"Missing required secret(s): {', '.join(missing)}. "
            f"Copy .env.example to .env and fill in values."
        )
    return Secrets(
        jira_email=jira_email,
        jira_api_token=jira_api_token,
        omada_clerk_token=omada_clerk_token,
    )


def load_team(team_name: str) -> dict:
    """Load config/teams/{team_name}.yaml as a plain dict.

    Team config validation is the simulator's responsibility (out of scope here).
    """
    path = TEAM_DIR / f"{team_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Team config not found: {path}. "
            f"Available: {sorted(p.stem for p in TEAM_DIR.glob('*.yaml'))}"
        )
    with path.open() as f:
        return yaml.safe_load(f)


def validate_safety(env: EnvironmentConfig) -> None:
    """Validate the environment config against its own safety rules.

    Raises SystemExit on any violation.
    """
    safety = env.safety

    if safety.refuse_with_message:
        raise SystemExit(safety.refuse_with_message.rstrip())

    url = env.omada.api_url

    if safety.required_url_substrings and not any(
        sub in url for sub in safety.required_url_substrings
    ):
        raise SystemExit(
            f"Safety violation: omada.api_url '{url}' does not contain any of "
            f"required substrings {safety.required_url_substrings} "
            f"for environment '{env.name}'."
        )

    for blocked in safety.block_url_substrings:
        if blocked in url:
            raise SystemExit(
                f"Safety violation: omada.api_url '{url}' contains blocked "
                f"substring '{blocked}' for environment '{env.name}'."
            )

    if not safety.allow_production and "production" in url:
        raise SystemExit(
            f"Safety violation: omada.api_url '{url}' contains 'production' "
            f"but allow_production is False for environment '{env.name}'."
        )


async def verify_connectivity(env: EnvironmentConfig, secrets: Secrets) -> None:
    """Ping the Omada API and verify the env looks like what the config claims.

    Steps:
    1. GET {api_url}/health to confirm reachability.
    2. GET {api_url}/api/organizations with Clerk token; count <= max_real_users_in_org.
    3. If require_simulated_org is True, confirm the active org has is_simulated=True.

    Raises SystemExit if any check fails.
    """
    base = env.omada.api_url.rstrip("/")
    headers = {"Authorization": f"Bearer {secrets.omada_clerk_token}"}

    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            health = await client.get(f"{base}/health")
        except httpx.HTTPError as e:
            raise SystemExit(
                f"Cannot reach Omada at {base}/health: {e}. "
                f"Is the Omada API running?"
            )
        if health.status_code >= 400:
            raise SystemExit(
                f"Omada /health returned {health.status_code} at {base}. "
                f"Body: {health.text[:200]}"
            )

        try:
            orgs_resp = await client.get(
                f"{base}/api/organizations", headers=headers
            )
        except httpx.HTTPError as e:
            raise SystemExit(f"Cannot reach Omada /api/organizations: {e}")

        if orgs_resp.status_code == 401:
            raise SystemExit(
                "Omada rejected OMADA_CLERK_TOKEN (401). "
                "Refresh the token from your browser cookies."
            )
        if orgs_resp.status_code >= 400:
            raise SystemExit(
                f"Omada /api/organizations returned {orgs_resp.status_code}. "
                f"Body: {orgs_resp.text[:200]}"
            )

        try:
            orgs = orgs_resp.json()
        except ValueError as e:
            raise SystemExit(f"Omada /api/organizations returned non-JSON: {e}")

        org_list = orgs if isinstance(orgs, list) else orgs.get("organizations", [])
        if len(org_list) > env.safety.max_real_users_in_org:
            raise SystemExit(
                f"Safety violation: Omada returned {len(org_list)} organizations, "
                f"exceeding max_real_users_in_org={env.safety.max_real_users_in_org}. "
                f"This environment looks larger than expected — refusing to proceed."
            )

        if env.safety.require_simulated_org:
            simulated = [o for o in org_list if o.get("is_simulated") is True]
            if not simulated:
                raise SystemExit(
                    "Safety violation: require_simulated_org=True but no organization "
                    "with is_simulated=True was found."
                )


def print_environment_banner(env: EnvironmentConfig, secrets: Secrets) -> None:
    """Print a clear banner showing which environment is active."""
    bar = "=" * 60
    allow_prod = "true" if env.safety.allow_production else "false"
    lines = [
        bar,
        f"Active environment: {env.name}",
        f"  Omada API: {env.omada.api_url}",
        f"  Jira:      {env.jira.url or '(none)'}",
        f"  Safety:    allow_production={allow_prod}, "
        f"max_users={env.safety.max_real_users_in_org}",
        bar,
    ]
    print("\n".join(lines))
