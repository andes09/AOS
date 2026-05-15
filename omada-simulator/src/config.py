"""Environment-aware configuration loading and safety validation."""

from __future__ import annotations

import os
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
    # Static key that pairs with SIMULATOR_API_KEY on the Omada side.
    # No refresh, no expiry — the API only honours it when ENVIRONMENT=local.
    omada_simulator_key: str = ""


def _available_envs() -> list[str]:
    return sorted(p.stem for p in ENV_DIR.glob("*.yaml"))


def load_environment(env_name: str) -> EnvironmentConfig:
    """Load and validate config/environments/{env_name}.yaml.

    Raises FileNotFoundError (with the list of available envs) if the file
    does not exist. Pydantic ValidationError bubbles up if the YAML is
    malformed.
    """
    path = ENV_DIR / f"{env_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Environment config not found: {path}. "
            f"Available environments: {_available_envs()}"
        )
    with path.open() as f:
        raw = yaml.safe_load(f)
    return EnvironmentConfig.model_validate(raw)


def load_secrets() -> Secrets:
    """Load .env and return a validated Secrets object.

    Jira creds are required; the simulator key is optional at load time
    so dry-runs can proceed without it. Empty strings are treated the
    same as missing.
    """
    load_dotenv(PACKAGE_ROOT / ".env")
    required = {
        "JIRA_EMAIL": os.getenv("JIRA_EMAIL"),
        "JIRA_API_TOKEN": os.getenv("JIRA_API_TOKEN"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit(
            f"Missing required secret(s): {', '.join(missing)}. "
            f"Copy .env.example to .env and fill in values."
        )
    return Secrets(
        jira_email=required["JIRA_EMAIL"],
        jira_api_token=required["JIRA_API_TOKEN"],
        omada_simulator_key=os.getenv("OMADA_SIMULATOR_KEY", "") or "",
    )


def load_team(team_name: str) -> dict:
    """Load config/teams/{team_name}.yaml as a plain dict.

    Team config validation is the simulator's responsibility.
    """
    path = TEAM_DIR / f"{team_name}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in TEAM_DIR.glob("*.yaml"))
        raise FileNotFoundError(
            f"Team config not found: {path}. Available teams: {available}"
        )
    with path.open() as f:
        return yaml.safe_load(f)


def validate_safety(env: EnvironmentConfig) -> None:
    """Validate the environment config against its own safety rules.

    Order matters:
    1. refuse_with_message — immediate SystemExit, no further checks.
    2. required_url_substrings — at least one must appear in the URL.
    3. block_url_substrings — none may appear in the URL.
    4. allow_production=False forbids any URL containing 'production'.
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


async def verify_connectivity(
    env: EnvironmentConfig,
    simulator_key: str,
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> None:
    """Probe Omada for liveness and auth.

    Step 1 — GET /health (expects 200).
    Step 2 — GET /api/me with X-Simulator-Key (expects 200; a 401 means
             the key doesn't match the API's SIMULATOR_API_KEY, or the
             API isn't running in local mode).

    The ``transport`` parameter exists for tests using
    ``httpx.MockTransport``; production callers pass nothing.
    """
    base = env.omada.api_url.rstrip("/")
    headers = {"X-Simulator-Key": simulator_key}

    client_kwargs: dict = {"timeout": httpx.Timeout(10.0)}
    if transport is not None:
        client_kwargs["transport"] = transport

    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            health = await client.get(f"{base}/health")
        except httpx.HTTPError as e:
            raise SystemExit(
                f"Omada not running at {base}. "
                f"Start with uvicorn src.main:app --reload from apps/api. "
                f"({e})"
            )
        if health.status_code >= 400:
            raise SystemExit(
                f"Omada /health returned {health.status_code} at {base}. "
                f"Body: {health.text[:200]}"
            )

        try:
            me = await client.get(f"{base}/api/me", headers=headers)
        except httpx.HTTPError as e:
            raise SystemExit(f"Cannot reach Omada /api/me: {e}")

        if me.status_code == 401:
            raise SystemExit(
                "Simulator key rejected. Check OMADA_SIMULATOR_KEY in "
                "omada-simulator/.env matches SIMULATOR_API_KEY in "
                "apps/api/.env, and that the API is running with "
                "ENVIRONMENT=local."
            )
        if me.status_code >= 400:
            raise SystemExit(
                f"Omada /api/me returned {me.status_code}. "
                f"Body: {me.text[:200]}"
            )


def print_environment_banner(env: EnvironmentConfig, secrets: Secrets) -> None:
    """Print a banner showing which environment is active."""
    bar = "=" * 60
    allow_prod = "true" if env.safety.allow_production else "false"
    lines = [
        bar,
        f"Active environment: {env.name}",
        f"  Omada API: {env.omada.api_url}",
        f"  Jira:      {env.jira.url or '(none)'}",
        f"  Safety:    allow_production={allow_prod}",
        bar,
    ]
    print("\n".join(lines))
