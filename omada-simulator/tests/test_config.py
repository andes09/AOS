"""Tests for src/config.py — loading, safety, secrets, connectivity, token resolution."""

from __future__ import annotations

import httpx
import pytest

from src.config import (
    EnvironmentConfig,
    JiraConfig,
    OmadaConfig,
    SafetyConfig,
    Secrets,
    load_environment,
    load_secrets,
    load_team,
    print_environment_banner,
    resolve_clerk_token,
    validate_safety,
    verify_connectivity,
)


# ---------- helpers ----------

def _make_env(
    *,
    name: str = "test",
    api_url: str = "http://localhost:8000",
    allow_production: bool = False,
    required: list[str] | None = None,
    blocked: list[str] | None = None,
    refuse: str | None = None,
) -> EnvironmentConfig:
    return EnvironmentConfig(
        name=name,
        description="test env",
        omada=OmadaConfig(api_url=api_url),
        jira=JiraConfig(url="https://example.atlassian.net", project_key_prefix="TST"),
        safety=SafetyConfig(
            allow_production=allow_production,
            required_url_substrings=required or [],
            block_url_substrings=blocked or [],
            refuse_with_message=refuse,
        ),
    )


def _secrets(token: str = "clerk-from-env") -> Secrets:
    return Secrets(
        jira_email="x@y.com",
        jira_api_token="t",
        omada_clerk_token=token,
    )


def _transport(handler):
    return httpx.MockTransport(handler)


# ---------- env loading ----------

def test_load_local_env_succeeds():
    env = load_environment("local")
    assert env.name == "local"
    assert env.omada.api_url == "http://localhost:8000"
    assert env.jira.project_key_prefix == "SIM"
    assert "localhost" in env.safety.required_url_substrings


def test_load_sims_env_succeeds():
    env = load_environment("sims")
    assert env.name == "sims"
    assert "sims" in env.omada.api_url
    assert "caboose" in env.safety.block_url_substrings


def test_load_nonexistent_env_raises_file_not_found():
    with pytest.raises(FileNotFoundError) as exc:
        load_environment("does_not_exist")
    msg = str(exc.value)
    assert "does_not_exist" in msg
    assert "local" in msg
    assert "sims" in msg


def test_prod_blocked_refuses_on_validate():
    env = load_environment("prod_blocked")
    with pytest.raises(SystemExit) as exc:
        validate_safety(env)
    assert "Refusing" in str(exc.value)
    assert "production" in str(exc.value).lower()


def test_safety_refuses_production_url():
    env = _make_env(api_url="https://api-production-2054.up.railway.app")
    with pytest.raises(SystemExit) as exc:
        validate_safety(env)
    assert "production" in str(exc.value)


def test_safety_requires_substring_match():
    env = _make_env(api_url="https://example.com", required=["sims"])
    with pytest.raises(SystemExit) as exc:
        validate_safety(env)
    assert "sims" in str(exc.value)


# ---------- secret loading ----------

def test_missing_jira_secrets_raises_system_exit(monkeypatch, tmp_path):
    """Jira creds are required; Clerk token is optional now since the
    practical workflow is --token at the CLI."""
    monkeypatch.setattr("src.config.PACKAGE_ROOT", tmp_path)
    for key in ("JIRA_EMAIL", "JIRA_API_TOKEN", "OMADA_CLERK_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit) as exc:
        load_secrets()
    msg = str(exc.value)
    assert "JIRA_EMAIL" in msg
    assert "JIRA_API_TOKEN" in msg


def test_missing_only_clerk_token_loads_successfully(monkeypatch, tmp_path):
    """Without a Clerk token in .env, load_secrets must still succeed —
    the user will pass --token at the CLI."""
    monkeypatch.setattr("src.config.PACKAGE_ROOT", tmp_path)
    monkeypatch.setenv("JIRA_EMAIL", "ok@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    monkeypatch.delenv("OMADA_CLERK_TOKEN", raising=False)
    s = load_secrets()
    assert s.omada_clerk_token == ""


def test_empty_jira_secret_treated_as_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.PACKAGE_ROOT", tmp_path)
    monkeypatch.setenv("JIRA_EMAIL", "ok@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "")
    monkeypatch.setenv("OMADA_CLERK_TOKEN", "clerk")
    with pytest.raises(SystemExit) as exc:
        load_secrets()
    assert "JIRA_API_TOKEN" in str(exc.value)


def test_secrets_loaded_from_env(monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.PACKAGE_ROOT", tmp_path)
    monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok-123")
    monkeypatch.setenv("OMADA_CLERK_TOKEN", "clerk-456")
    s = load_secrets()
    assert s.jira_email == "test@example.com"
    assert s.jira_api_token == "tok-123"
    assert s.omada_clerk_token == "clerk-456"


# ---------- resolve_clerk_token ----------

def test_resolve_clerk_token_prefers_cli_over_env():
    s = _secrets(token="from-env")
    assert resolve_clerk_token("from-cli", s) == "from-cli"


def test_resolve_clerk_token_falls_back_to_env():
    s = _secrets(token="from-env")
    assert resolve_clerk_token(None, s) == "from-env"


def test_resolve_clerk_token_empty_cli_uses_env():
    s = _secrets(token="from-env")
    assert resolve_clerk_token("", s) == "from-env"


def test_resolve_clerk_token_errors_when_neither_set():
    s = _secrets(token="")
    with pytest.raises(SystemExit) as exc:
        resolve_clerk_token(None, s)
    msg = str(exc.value)
    assert "--token" in msg
    assert "window.Clerk.session.getToken" in msg


# ---------- team loading & safety supplemental ----------

def test_load_team_succeeds():
    team = load_team("stage1_team")
    assert team["team_name"] == "Stage1 Test Team"
    assert len(team["developers"]) == 4
    assert team["developers"][0]["name"] == "Alex"


def test_unknown_team_raises():
    with pytest.raises(FileNotFoundError):
        load_team("ghost_team")


def test_validate_safety_passes_for_local():
    validate_safety(load_environment("local"))


def test_validate_safety_passes_for_sims():
    validate_safety(load_environment("sims"))


def test_safety_required_substring_satisfied():
    env = _make_env(api_url="https://api-sims.example.com", required=["sims"])
    validate_safety(env)


def test_safety_blocks_url_substring():
    env = _make_env(api_url="https://caboose.example.com", blocked=["caboose"])
    with pytest.raises(SystemExit) as exc:
        validate_safety(env)
    assert "caboose" in str(exc.value)


def test_safety_allow_production_permits_production_url():
    env = _make_env(
        api_url="https://api-production-2054.up.railway.app",
        allow_production=True,
    )
    validate_safety(env)


def test_print_environment_banner(capsys):
    env = load_environment("local")
    print_environment_banner(env, _secrets())
    out = capsys.readouterr().out
    assert "Active environment: local" in out
    assert "http://localhost:8000" in out
    assert "allow_production=false" in out


# ---------- connectivity tests ----------

@pytest.mark.asyncio
async def test_verify_connectivity_succeeds():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/me":
            assert req.headers.get("Authorization") == "Bearer clerk"
            return httpx.Response(200, json={"id": "user_123"})
        return httpx.Response(404)

    env = _make_env(api_url="http://localhost:8000")
    await verify_connectivity(env, "clerk", transport=_transport(handler))


@pytest.mark.asyncio
async def test_verify_connectivity_health_unreachable():
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, "clerk", transport=_transport(handler))
    assert "Omada not running" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_connectivity_health_5xx():
    def handler(req):
        return httpx.Response(500, text="boom")

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, "clerk", transport=_transport(handler))
    assert "/health returned 500" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_connectivity_me_401_guides_to_fresh_token():
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(401, text="unauthorized")

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, "stale", transport=_transport(handler))
    msg = str(exc.value)
    assert "expired" in msg
    assert "--token" in msg
    assert "window.Clerk.session.getToken" in msg


@pytest.mark.asyncio
async def test_verify_connectivity_me_5xx_shows_body():
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(500, text="db down")

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, "clerk", transport=_transport(handler))
    assert "/api/me returned 500" in str(exc.value)
    assert "db down" in str(exc.value)
