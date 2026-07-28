"""
Tests for the Omada MCP OAuth 2.1 Authorization Server (mcp_server/
oauth_provider.py, routers/mcp_oauth_consent.py) and the 9 MCP tools
(mcp_server/tools.py):

- experimental.mcp_server feature-flag gate (404 while off)
- full OAuth flow: dynamic client registration -> Clerk-gated consent ->
  authorization-code exchange (with PKCE) -> a bearer token that resolves
  back to the right org/developer
- per-tool org-scoping, project_id resolution, get_next_task's self-
  assignment, complete_task's idempotency, regenerate_milestone's role +
  confirmation gates
"""

import base64
import hashlib
import secrets
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import src.database as database_module
from src.config import settings
from src.database import Base, get_db
from src.main import app
from src.mcp_server.oauth_provider import OmadaOAuthProvider
from src.mcp_server import tools as mcp_tools
from src.models.developer import Developer
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team

ORG = "org_mcp_test"
USER = "user_mcp_test"
AUTH = {"Authorization": "Bearer tok"}


@pytest_asyncio.fixture
async def mcp_db():
    """Like conftest's `tmp_db`, but ALSO patches `src.database.AsyncSessionLocal`
    to the same in-memory sqlite engine (same pattern as test_cost_tracker.py's
    `cost_db` fixture). oauth_provider.py/tools.py call `src.database.db_session()`
    directly — never through FastAPI's `Depends(get_db)` — so `tmp_db` alone
    (which only overrides the FastAPI dependency) would leave them talking to
    the real, unconfigured production engine instead of this test's data."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with patch.object(database_module, "AsyncSessionLocal", Session):
        yield
    app.dependency_overrides.pop(get_db, None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _patch_clerk(user_id=USER, org_id=ORG):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _enable_flag(enabled: bool = True):
    """Same idiom as test_artifact_import.py/test_platform_admin.py: patch
    Settings.is_feature_enabled at the class level for this one flag, real
    behavior preserved for every other flag."""
    real = type(settings).is_feature_enabled

    def fake(self, flag_name: str) -> bool:
        if flag_name == "experimental.mcp_server":
            return enabled
        return real(self, flag_name)

    return patch.object(type(settings), "is_feature_enabled", fake)


async def _seed(clerk_org_id=ORG, clerk_user_id=USER):
    org_id, team_id, dev_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(Organization(id=org_id, clerk_org_id=clerk_org_id, name="Test Org", slug=clerk_org_id, use_managed_key=False))
        await db.flush()
        db.add(Team(id=team_id, organization_id=org_id, name="Default"))
        await db.flush()
        db.add(Developer(id=dev_id, team_id=team_id, name="Ada", clerk_user_id=clerk_user_id, app_role="lead", is_active=True))
        await db.commit()
        return org_id, team_id, dev_id


async def _seed_project(org_id, team_id, name="Proj", status="active"):
    project_id, session_id, m_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(OnboardingSession(id=session_id, organization_id=org_id, status="completed", project_brief={"projectName": name}))
        await db.flush()
        db.add(Project(id=project_id, team_id=team_id, onboarding_session_id=session_id, name=name, status=status))
        await db.flush()
        db.add(Milestone(id=m_id, project_id=project_id, title="M1", sort_order=0))
        await db.flush()
        db.add(Task(milestone_id=m_id, title="T0", status="todo", sort_order=0))
        db.add(Task(milestone_id=m_id, title="T1", status="todo", sort_order=1))
        await db.commit()
        return project_id, m_id


def _pkce_pair():
    verifier = secrets.token_urlsafe(43)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


# ─── feature flag gate ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_consent_404_when_flag_off(mcp_db):
    await _seed()
    with _enable_flag(False), _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                "/api/mcp/oauth/consent",
                json={"clientId": "x", "redirectUri": "http://x", "codeChallenge": "y"},
                headers=AUTH,
            )
    assert resp.status_code == 404


# ─── full OAuth flow ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_full_oauth_flow_issues_scoped_token(mcp_db):
    org_id, team_id, dev_id = await _seed()
    provider = OmadaOAuthProvider()
    verifier, challenge = _pkce_pair()

    # 1. Dynamic client registration.
    with _enable_flag(True):
        async with _client() as client:
            reg = await client.post(
                "/register",
                json={
                    "client_name": "test-agent",
                    "redirect_uris": ["http://localhost:9999/callback"],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "token_endpoint_auth_method": "none",
                },
            )
        assert reg.status_code == 201, reg.text
        client_id = reg.json()["client_id"]

        # 2. Consent (Clerk-gated) — mints an authorization code.
        with _patch_clerk():
            async with _client() as client:
                consent_resp = await client.post(
                    "/api/mcp/oauth/consent",
                    json={
                        "clientId": client_id,
                        "redirectUri": "http://localhost:9999/callback",
                        "codeChallenge": challenge,
                        "scope": "roadmap",
                        "state": "xyz",
                    },
                    headers=AUTH,
                )
        assert consent_resp.status_code == 200, consent_resp.text
        redirect_url = consent_resp.json()["redirectUrl"]
        assert "code=" in redirect_url
        code = redirect_url.split("code=")[1].split("&")[0]

        # 3. Token exchange (PKCE verified by the SDK itself).
        async with _client() as client:
            token_resp = await client.post(
                "/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "http://localhost:9999/callback",
                    "client_id": client_id,
                    "code_verifier": verifier,
                },
            )
        assert token_resp.status_code == 200, token_resp.text
        access_token = token_resp.json()["access_token"]

    # 4. The minted token resolves back to the seeded org/developer.
    loaded = await provider.load_access_token(access_token)
    assert loaded is not None
    assert loaded.claims["clerk_org_id"] == ORG
    assert loaded.claims["clerk_user_id"] == USER
    assert loaded.claims["developer_id"] == str(dev_id)


@pytest.mark.asyncio
async def test_consent_409_without_developer_record(mcp_db):
    """Open risk #1 from the plan doc: a connecting Clerk user with no
    Developer row can't be minted a usable token."""
    org_id, team_id, dev_id = await _seed()
    provider = OmadaOAuthProvider()
    client_info_id = None
    with _enable_flag(True):
        async with _client() as client:
            reg = await client.post(
                "/register",
                json={
                    "redirect_uris": ["http://localhost:9999/callback"],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "token_endpoint_auth_method": "none",
                },
            )
        assert reg.status_code == 201, reg.text
        client_id = reg.json()["client_id"]
        with _patch_clerk(user_id="user_with_no_developer_row"):
            async with _client() as client:
                resp = await client.post(
                    "/api/mcp/oauth/consent",
                    json={"clientId": client_id, "redirectUri": "http://localhost:9999/callback", "codeChallenge": "abc"},
                    headers=AUTH,
                )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_developer_record"


# ─── per-tool tests ──────────────────────────────────────────────────────────
def _fake_access_token(org_id, clerk_user_id, dev_id):
    from mcp.server.auth.middleware.auth_context import auth_context_var, AuthenticatedUser
    from mcp.server.auth.provider import AccessToken

    at = AccessToken(
        token="fake", client_id="test-client", scopes=["roadmap"],
        claims={"clerk_org_id": ORG, "clerk_user_id": clerk_user_id, "developer_id": str(dev_id)},
    )
    token = auth_context_var.set(AuthenticatedUser(at))
    return token


def _clear_access_token(token):
    from mcp.server.auth.middleware.auth_context import auth_context_var
    auth_context_var.reset(token)


class _FakeMCP:
    """Captures @mcp.tool()-registered functions by name for direct invocation
    in tests, bypassing the wire transport entirely."""

    def __init__(self):
        self.tools = {}

    def tool(self, *_a, **_k):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


@pytest.fixture
def registered_tools():
    fake = _FakeMCP()
    mcp_tools.register_tools(fake)
    return fake.tools


@pytest.mark.asyncio
async def test_list_projects_scoped_to_org(registered_tools, mcp_db):
    org_id, team_id, dev_id = await _seed()
    p1, _ = await _seed_project(org_id, team_id, name="A")

    other_org, other_team, _ = await _seed(clerk_org_id="other_org", clerk_user_id="other_user")
    await _seed_project(other_org, other_team, name="B")

    token = _fake_access_token(org_id, USER, dev_id)
    try:
        result = await registered_tools["list_projects"]()
    finally:
        _clear_access_token(token)
    names = [p["name"] for p in result["projects"]]
    assert names == ["A"]


@pytest.mark.asyncio
async def test_get_next_task_self_assigns(registered_tools, mcp_db):
    org_id, team_id, dev_id = await _seed()
    project_id, m_id = await _seed_project(org_id, team_id)

    token = _fake_access_token(org_id, USER, dev_id)
    try:
        result = await registered_tools["get_next_task"](project_id=str(project_id))
    finally:
        _clear_access_token(token)
    assert result["task"]["title"] == "T0"
    assert result["task"]["assigneeId"] == str(dev_id)


@pytest.mark.asyncio
async def test_get_next_task_default_project_when_exactly_one_active(registered_tools, mcp_db):
    org_id, team_id, dev_id = await _seed()
    await _seed_project(org_id, team_id)

    token = _fake_access_token(org_id, USER, dev_id)
    try:
        result = await registered_tools["get_next_task"]()  # project_id omitted
    finally:
        _clear_access_token(token)
    assert result["task"] is not None


@pytest.mark.asyncio
async def test_get_next_task_requires_project_id_when_ambiguous(registered_tools, mcp_db):
    org_id, team_id, dev_id = await _seed()
    await _seed_project(org_id, team_id, name="A")
    await _seed_project(org_id, team_id, name="B")

    token = _fake_access_token(org_id, USER, dev_id)
    try:
        with pytest.raises(mcp_tools.ToolError):
            await registered_tools["get_next_task"]()
    finally:
        _clear_access_token(token)


@pytest.mark.asyncio
async def test_complete_task_idempotent_note(registered_tools, mcp_db):
    org_id, team_id, dev_id = await _seed()
    project_id, m_id = await _seed_project(org_id, team_id)

    async for db in app.dependency_overrides[get_db]():
        task_id = (await db.scalar(select(Task).where(Task.milestone_id == m_id))).id
        break

    token = _fake_access_token(org_id, USER, dev_id)
    try:
        r1 = await registered_tools["complete_task"](task_id=str(task_id), completion_note="did it", project_id=str(project_id))
        assert r1["task"]["completionNote"] == "did it"
        # Re-calling without a note must not clobber the prior one.
        r2 = await registered_tools["complete_task"](task_id=str(task_id), completion_note=None, project_id=str(project_id))
        assert r2["task"]["completionNote"] == "did it"
        assert r2["task"]["status"] == "done"
    finally:
        _clear_access_token(token)


@pytest.mark.asyncio
async def test_regenerate_milestone_requires_confirmation(registered_tools, mcp_db):
    org_id, team_id, dev_id = await _seed()
    project_id, m_id = await _seed_project(org_id, team_id)

    token = _fake_access_token(org_id, USER, dev_id)
    try:
        result = await registered_tools["regenerate_milestone"](milestone_id=str(m_id), confirmed=False, project_id=str(project_id))
    finally:
        _clear_access_token(token)
    assert result["error"] == "confirmation_required"


@pytest.mark.asyncio
async def test_regenerate_milestone_requires_lead_role(registered_tools, mcp_db):
    org_id, team_id, _lead_dev_id = await _seed()
    project_id, m_id = await _seed_project(org_id, team_id)

    dev_only_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(Developer(id=dev_only_id, team_id=team_id, name="Bob", clerk_user_id="bob", app_role="developer", is_active=True))
        await db.commit()
        break

    token = _fake_access_token(org_id, "bob", dev_only_id)
    try:
        result = await registered_tools["regenerate_milestone"](milestone_id=str(m_id), confirmed=True, project_id=str(project_id))
    finally:
        _clear_access_token(token)
    assert result["error"] == "requires_lead_role"


@pytest.mark.asyncio
async def test_get_task_cross_project_within_org_404(registered_tools, mcp_db):
    org_id, team_id, dev_id = await _seed()
    project_a, m_a = await _seed_project(org_id, team_id, name="A")
    project_b, m_b = await _seed_project(org_id, team_id, name="B")

    async for db in app.dependency_overrides[get_db]():
        task_a = (await db.scalar(select(Task).where(Task.milestone_id == m_a))).id
        break

    token = _fake_access_token(org_id, USER, dev_id)
    try:
        with pytest.raises(Exception):  # HTTPException(404) — surfaced as a tool error by FastMCP in real use
            await registered_tools["get_task"](task_id=str(task_a), project_id=str(project_b))
    finally:
        _clear_access_token(token)
