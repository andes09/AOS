"""Tests for src/config.py — loading, safety validation, secrets, connectivity."""

from __future__ import annotations

import httpx
import pytest

from src.clerk_auth import ClerkAuth
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


def _secrets() -> Secrets:
    return Secrets(
        jira_email="x@y.com",
        jira_api_token="t",
        omada_email="sim@example.com",
        omada_password="hunter2",
        clerk_publishable_key="pk_test_c2luY2VyZS1yaGluby0wLmNsZXJrLmFjY291bnRzLmRldiQ",
    )


class _StubAuth:
    """Lightweight ClerkAuth stand-in for verify_connectivity tests.

    We don't want connectivity tests to depend on Clerk's Frontend API
    being mocked end-to-end — they only care that the token we return
    rides in the /api/me request.
    """

    def __init__(self, token: str = "stub-jwt") -> None:
        self._token = token

    def get_token(self) -> str:
        return self._token


def _transport(handler):
    return httpx.MockTransport(handler)


# ---------- spec-named tests ----------

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
    # Error must list the available environments so the user can self-correct.
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


def test_missing_secrets_raises_system_exit(monkeypatch, tmp_path):
    # Point .env resolution at an empty tmp dir so the real .env can't leak in.
    monkeypatch.setattr("src.config.PACKAGE_ROOT", tmp_path)
    for key in (
        "JIRA_EMAIL",
        "JIRA_API_TOKEN",
        "OMADA_EMAIL",
        "OMADA_PASSWORD",
        "CLERK_PUBLISHABLE_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit) as exc:
        load_secrets()
    msg = str(exc.value)
    # All five missing secrets must be listed in a single error message.
    assert "JIRA_EMAIL" in msg
    assert "JIRA_API_TOKEN" in msg
    assert "OMADA_EMAIL" in msg
    assert "OMADA_PASSWORD" in msg
    assert "CLERK_PUBLISHABLE_KEY" in msg


def test_empty_secret_treated_as_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.PACKAGE_ROOT", tmp_path)
    monkeypatch.setenv("JIRA_EMAIL", "ok@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "")
    monkeypatch.setenv("OMADA_EMAIL", "sim@example.com")
    monkeypatch.setenv("OMADA_PASSWORD", "hunter2")
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_xyz")
    with pytest.raises(SystemExit) as exc:
        load_secrets()
    msg = str(exc.value)
    assert "JIRA_API_TOKEN" in msg
    # Set secrets must not be flagged
    assert "JIRA_EMAIL" not in msg
    assert "OMADA_PASSWORD" not in msg


def test_load_team_succeeds():
    team = load_team("stage1_team")
    assert team["team_name"] == "Stage1 Test Team"
    assert len(team["developers"]) == 4
    assert team["developers"][0]["name"] == "Alex"


def test_unknown_team_raises():
    with pytest.raises(FileNotFoundError):
        load_team("ghost_team")


# ---------- supplementary coverage ----------

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


def test_secrets_loaded_from_env(monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.PACKAGE_ROOT", tmp_path)
    monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok-123")
    monkeypatch.setenv("OMADA_EMAIL", "sim@example.com")
    monkeypatch.setenv("OMADA_PASSWORD", "hunter2")
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_xyz")
    s = load_secrets()
    assert s.jira_email == "test@example.com"
    assert s.jira_api_token == "tok-123"
    assert s.omada_email == "sim@example.com"
    assert s.omada_password == "hunter2"
    assert s.clerk_publishable_key == "pk_test_xyz"


def test_print_environment_banner(capsys):
    env = load_environment("local")
    print_environment_banner(env, _secrets())
    out = capsys.readouterr().out
    assert "Active environment: local" in out
    assert "http://localhost:8000" in out
    assert "allow_production=false" in out


# ---------- connectivity tests (httpx.MockTransport) ----------

@pytest.mark.asyncio
async def test_verify_connectivity_succeeds():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/me":
            assert req.headers.get("Authorization") == "Bearer stub-jwt"
            return httpx.Response(200, json={"id": "user_123"})
        return httpx.Response(404)

    env = _make_env(api_url="http://localhost:8000")
    await verify_connectivity(env, _StubAuth(), transport=_transport(handler))


@pytest.mark.asyncio
async def test_verify_connectivity_health_unreachable():
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, _StubAuth(), transport=_transport(handler))
    assert "Omada not running" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_connectivity_health_5xx():
    def handler(req):
        return httpx.Response(500, text="boom")

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, _StubAuth(), transport=_transport(handler))
    assert "/health returned 500" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_connectivity_me_401_blames_account_not_token():
    """A 401 used to mean a stale pasted cookie. Now we always mint a fresh
    token at request time, so a 401 means the signed-in account isn't a
    known Omada user — surface that distinct message instead.
    """
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(401, text="unauthorized")

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, _StubAuth(), transport=_transport(handler))
    msg = str(exc.value)
    assert "freshly-minted Clerk token" in msg
    assert "OMADA_EMAIL" in msg


@pytest.mark.asyncio
async def test_verify_connectivity_me_5xx_shows_body():
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(500, text="db down")

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, _StubAuth(), transport=_transport(handler))
    assert "/api/me returned 500" in str(exc.value)
    assert "db down" in str(exc.value)


# Type-only smoke test: _StubAuth must satisfy the duck-typed protocol
# expected by verify_connectivity. ClerkAuth has the same shape.
def test_stub_auth_matches_clerk_auth_protocol():
    assert hasattr(ClerkAuth, "get_token")
    assert hasattr(_StubAuth(), "get_token")
