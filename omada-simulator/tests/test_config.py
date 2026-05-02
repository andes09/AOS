"""Tests for src/config.py — loading, safety validation, and secret parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

import httpx

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


def _make_env(
    *,
    name: str = "test",
    api_url: str = "http://localhost:8000",
    allow_production: bool = False,
    required: list[str] | None = None,
    blocked: list[str] | None = None,
    refuse: str | None = None,
    max_users: int = 5,
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
            max_real_users_in_org=max_users,
            refuse_with_message=refuse,
        ),
    )


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


def test_load_prod_blocked_env_succeeds():
    env = load_environment("prod_blocked")
    assert env.safety.refuse_with_message is not None
    assert "Refusing" in env.safety.refuse_with_message


def test_load_nonexistent_env_raises():
    with pytest.raises(FileNotFoundError):
        load_environment("does_not_exist")


def test_load_typo_env_raises_filenotfounderror():
    with pytest.raises(FileNotFoundError) as exc:
        load_environment("locall")
    assert "locall" in str(exc.value)


def test_validate_safety_passes_for_local():
    env = load_environment("local")
    validate_safety(env)


def test_validate_safety_passes_for_sims():
    env = load_environment("sims")
    validate_safety(env)


def test_prod_blocked_raises_on_validate():
    env = load_environment("prod_blocked")
    with pytest.raises(SystemExit) as exc:
        validate_safety(env)
    assert "Refusing" in str(exc.value)


def test_safety_refuses_production_url():
    env = _make_env(api_url="https://api-production-2054.up.railway.app")
    with pytest.raises(SystemExit) as exc:
        validate_safety(env)
    assert "production" in str(exc.value)


def test_safety_allow_production_permits_production_url():
    env = _make_env(
        api_url="https://api-production-2054.up.railway.app",
        allow_production=True,
    )
    validate_safety(env)


def test_safety_requires_substring():
    env = _make_env(api_url="https://example.com", required=["sims"])
    with pytest.raises(SystemExit) as exc:
        validate_safety(env)
    assert "sims" in str(exc.value)


def test_safety_required_substring_satisfied():
    env = _make_env(api_url="https://api-sims.example.com", required=["sims"])
    validate_safety(env)


def test_safety_blocks_url_substring():
    env = _make_env(api_url="https://caboose.example.com", blocked=["caboose"])
    with pytest.raises(SystemExit) as exc:
        validate_safety(env)
    assert "caboose" in str(exc.value)


def test_secrets_loaded_from_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok-123")
    monkeypatch.setenv("OMADA_CLERK_TOKEN", "clerk-456")
    secrets = load_secrets()
    assert secrets.jira_email == "test@example.com"
    assert secrets.jira_api_token == "tok-123"
    assert secrets.omada_clerk_token == "clerk-456"


def test_secrets_missing_raises(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.delenv("OMADA_CLERK_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        load_secrets()
    assert "JIRA_EMAIL" in str(exc.value)


def test_load_team_returns_dict():
    team = load_team("stage1_team")
    assert team["team_name"] == "Stage1 Test Team"
    assert len(team["developers"]) == 4
    assert team["developers"][0]["name"] == "Alex"


def test_load_team_nonexistent_raises():
    with pytest.raises(FileNotFoundError):
        load_team("ghost_team")


def _secrets() -> Secrets:
    return Secrets(
        jira_email="x@y.com", jira_api_token="t", omada_clerk_token="c"
    )


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_verify_connectivity_succeeds():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/organizations":
            assert req.headers.get("Authorization") == "Bearer c"
            return httpx.Response(200, json=[{"id": 1, "is_simulated": True}])
        return httpx.Response(404)

    env = _make_env(api_url="http://localhost:8000", max_users=5)
    await verify_connectivity(env, _secrets(), transport=_transport(handler))


@pytest.mark.asyncio
async def test_verify_connectivity_health_unreachable():
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, _secrets(), transport=_transport(handler))
    assert "Cannot reach Omada" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_connectivity_health_500():
    def handler(req):
        return httpx.Response(500, text="boom")

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, _secrets(), transport=_transport(handler))
    assert "/health returned 500" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_connectivity_orgs_401():
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(401, text="unauthorized")

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, _secrets(), transport=_transport(handler))
    assert "401" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_connectivity_orgs_500():
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(500, text="server error")

    env = _make_env()
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, _secrets(), transport=_transport(handler))
    assert "500" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_connectivity_too_many_orgs():
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(200, json=[{"id": i} for i in range(50)])

    env = _make_env(max_users=5)
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, _secrets(), transport=_transport(handler))
    assert "max_real_users_in_org" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_connectivity_requires_simulated_org():
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(200, json=[{"id": 1, "is_simulated": False}])

    env = _make_env()
    env.safety.require_simulated_org = True
    with pytest.raises(SystemExit) as exc:
        await verify_connectivity(env, _secrets(), transport=_transport(handler))
    assert "is_simulated" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_connectivity_orgs_dict_envelope():
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(
            200, json={"organizations": [{"id": 1, "is_simulated": True}]}
        )

    env = _make_env()
    env.safety.require_simulated_org = True
    await verify_connectivity(env, _secrets(), transport=_transport(handler))


def test_print_environment_banner(capsys):
    env = load_environment("local")
    secrets = type(
        "S",
        (),
        {"jira_email": "x@y", "jira_api_token": "t", "omada_clerk_token": "c"},
    )()
    print_environment_banner(env, secrets)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "Active environment: local" in out
    assert "http://localhost:8000" in out
    assert "allow_production=false" in out
