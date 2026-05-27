"""Tests for PATCH /api/sprints/{sprint_id}/assignments/{ticket_id} (M8a).

Follows the MagicMock pattern used elsewhere in this suite (see
test_sprints_router.py). NO tmp_db / live DB.
"""
import uuid
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


ORG_CLERK_ID = "org_override_test"
ORG_ID = uuid.uuid4()
TEAM_ID = uuid.uuid4()
SPRINT_ID = uuid.uuid4()
TICKET_ID = uuid.uuid4()
ORIGINAL_DEV_ID = uuid.uuid4()
NEW_DEV_ID = uuid.uuid4()
LEAD_USER_ID = "user_lead_clerk"
LEAD_DEV_ID = uuid.uuid4()


def _make_org():
    o = MagicMock()
    o.id = ORG_ID
    o.clerk_org_id = ORG_CLERK_ID
    return o


def _make_other_org():
    o = MagicMock()
    o.id = ORG_ID
    o.clerk_org_id = "org_someone_else"
    return o


def _make_team():
    t = MagicMock()
    t.id = TEAM_ID
    t.organization_id = ORG_ID
    return t


def _make_sprint():
    s = MagicMock()
    s.id = SPRINT_ID
    s.team_id = TEAM_ID
    return s


def _make_ticket(sprint_id=SPRINT_ID, assignee_id=ORIGINAL_DEV_ID):
    t = MagicMock()
    t.id = TICKET_ID
    t.sprint_id = sprint_id
    t.assignee_id = assignee_id
    return t


def _make_actor_dev():
    d = MagicMock()
    d.id = LEAD_DEV_ID
    d.clerk_user_id = LEAD_USER_ID
    return d


def _setup_session(scalar_results, captured_adds=None):
    """Build a fake AsyncSession whose .scalar() returns items from scalar_results
    in order, and whose .add() appends to captured_adds (if provided)."""
    session = MagicMock()
    state = {"i": 0}

    async def fake_scalar(_q):
        i = state["i"]
        state["i"] += 1
        return scalar_results[i] if i < len(scalar_results) else None

    async def fake_commit():
        return None

    def fake_add(obj):
        if captured_adds is not None:
            captured_adds.append(obj)

    session.scalar = fake_scalar
    session.commit = fake_commit
    session.add = fake_add
    return session


def _install_overrides(app, session, role="lead"):
    from src.auth import get_current_org_id, get_current_user_id
    from src.auth_roles import get_current_app_role
    from src.database import get_db

    async def _db():
        yield session

    async def _user():
        return LEAD_USER_ID

    async def _org():
        return ORG_CLERK_ID

    async def _role_dep():
        return role

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_org_id] = _org
    app.dependency_overrides[get_current_app_role] = _role_dep


@pytest.mark.asyncio
async def test_reassign_mutates_ticket_and_writes_override():
    from src.main import app

    ticket = _make_ticket()
    actor = _make_actor_dev()
    # router queries: Sprint, Team, Organization, Ticket, Developer(actor)
    session = _setup_session(
        [_make_sprint(), _make_team(), _make_org(), ticket, actor],
        captured_adds=[],
    )
    captured = []
    session.add = captured.append

    _install_overrides(app, session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/sprints/{SPRINT_ID}/assignments/{TICKET_ID}",
                json={
                    "newDeveloperId": str(NEW_DEV_ID),
                    "action": "reassign",
                    "reasonCode": "skill_fit",
                    "reasonText": "stronger React match",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["assigneeId"] == str(NEW_DEV_ID)
    # Ticket.assignee_id mutated on the same object
    assert ticket.assignee_id == NEW_DEV_ID
    # Exactly one override row added with correct fields
    assert len(captured) == 1
    o = captured[0]
    assert str(o.sprint_id) == str(SPRINT_ID)
    assert str(o.ticket_id) == str(TICKET_ID)
    assert o.action == "reassign"
    assert o.original_developer_id == ORIGINAL_DEV_ID
    assert o.new_developer_id == NEW_DEV_ID
    assert o.reason_code == "skill_fit"
    assert o.reason_text == "stronger React match"
    assert o.created_by == LEAD_DEV_ID


@pytest.mark.asyncio
async def test_remove_clears_assignee_and_writes_override():
    from src.main import app

    ticket = _make_ticket()
    actor = _make_actor_dev()
    session = _setup_session(
        [_make_sprint(), _make_team(), _make_org(), ticket, actor]
    )
    captured = []
    session.add = captured.append

    _install_overrides(app, session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/sprints/{SPRINT_ID}/assignments/{TICKET_ID}",
                json={
                    "newDeveloperId": None,
                    "action": "remove",
                    "reasonCode": "pto",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["assigneeId"] is None
    assert ticket.assignee_id is None
    assert len(captured) == 1
    o = captured[0]
    assert o.action == "remove"
    # remove always nulls new_developer_id even if one was sent
    assert o.new_developer_id is None
    assert o.original_developer_id == ORIGINAL_DEV_ID


@pytest.mark.asyncio
async def test_null_reason_code_allowed():
    from src.main import app

    ticket = _make_ticket()
    actor = _make_actor_dev()
    session = _setup_session(
        [_make_sprint(), _make_team(), _make_org(), ticket, actor]
    )
    captured = []
    session.add = captured.append

    _install_overrides(app, session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/sprints/{SPRINT_ID}/assignments/{TICKET_ID}",
                json={
                    "newDeveloperId": str(NEW_DEV_ID),
                    "action": "reassign",
                    "reasonCode": None,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert len(captured) == 1
    assert captured[0].reason_code is None


@pytest.mark.asyncio
async def test_non_lead_role_returns_403():
    from src.main import app

    session = _setup_session([])
    _install_overrides(app, session, role="developer")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/sprints/{SPRINT_ID}/assignments/{TICKET_ID}",
                json={
                    "newDeveloperId": str(NEW_DEV_ID),
                    "action": "reassign",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_foreign_org_sprint_returns_404():
    from src.main import app

    # Sprint and Team resolve, but Organization belongs to a different clerk org.
    session = _setup_session([_make_sprint(), _make_team(), _make_other_org()])

    _install_overrides(app, session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/sprints/{SPRINT_ID}/assignments/{TICKET_ID}",
                json={
                    "newDeveloperId": str(NEW_DEV_ID),
                    "action": "reassign",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ticket_not_in_sprint_returns_422():
    from src.main import app

    # Ticket exists but belongs to a different sprint.
    other_sprint = uuid.uuid4()
    ticket = _make_ticket(sprint_id=other_sprint)
    session = _setup_session([_make_sprint(), _make_team(), _make_org(), ticket])

    _install_overrides(app, session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/sprints/{SPRINT_ID}/assignments/{TICKET_ID}",
                json={
                    "newDeveloperId": str(NEW_DEV_ID),
                    "action": "reassign",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
