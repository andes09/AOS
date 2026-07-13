import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.services.idea_interview import (
    _system_prompt,
    merge_brief,
    missing_fields,
    opening_message,
    resolve_api_key,
)

ORG = "org_chat_test"
USER = "user_chat"
AUTH = {"Authorization": "Bearer tok"}


def _patch_clerk(user_id=USER, org_id=ORG):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _start_chat(client, purpose="startup"):
    """chat/start now requires a purpose to be set first (gates the system prompt)."""
    await client.put("/api/onboarding/v2/purpose", json={"purpose": purpose}, headers=AUTH)
    return await client.post("/api/onboarding/v2/chat/start", headers=AUTH)


async def _seed_org_and_team(clerk_org_id=ORG, anthropic_key=None):
    from src.database import get_db
    from src.models.organization import Organization
    from src.models.team import Team
    from src.services.encryption import encrypt

    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=uuid.uuid4(),
            clerk_org_id=clerk_org_id,
            name="Test Org",
            slug=clerk_org_id,
            use_managed_key=False,
            encrypted_anthropic_key=encrypt(anthropic_key) if anthropic_key else None,
        )
        db.add(org)
        await db.flush()
        db.add(Team(id=uuid.uuid4(), organization_id=org.id, name="Default"))
        await db.commit()
        return org.id


# ---------------------------------------------------------------------------
# Fake Anthropic client: supports messages.stream(...) and messages.create(...)
# ---------------------------------------------------------------------------

class _FakeUsage:
    input_tokens = 10
    output_tokens = 20
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @property
    def text_stream(self):
        async def gen():
            for c in self._chunks:
                yield c
        return gen()

    async def get_final_message(self):
        msg = type("M", (), {})()
        msg.usage = _FakeUsage()
        return msg


class _FakeToolBlock:
    type = "tool_use"
    name = "update_project_brief"

    def __init__(self, payload):
        self.input = payload


def _fake_anthropic(reply_chunks, extraction_payload):
    """Build a fake anthropic.AsyncAnthropic replacement."""
    extraction_response = type("R", (), {})()
    extraction_response.usage = _FakeUsage()
    extraction_response.content = [_FakeToolBlock(extraction_payload)]

    fake = type("FakeClient", (), {})()
    fake.messages = type("M", (), {})()
    fake.messages.stream = lambda **kw: _FakeStream(reply_chunks)
    fake.messages.create = AsyncMock(return_value=extraction_response)
    return fake


# ---------------------------------------------------------------------------
# Unit tests: brief merge + missing fields + key resolution
# ---------------------------------------------------------------------------

def test_merge_brief_scalars_not_erased_by_null():
    current = {"projectName": "Roadmapper", "coreFeatures": ["chat"]}
    extracted = {"projectName": None, "problemStatement": "planning is hard", "coreFeatures": []}
    merged = merge_brief(current, extracted)
    assert merged["projectName"] == "Roadmapper"
    assert merged["problemStatement"] == "planning is hard"
    assert merged["coreFeatures"] == ["chat"]


def test_merge_brief_lists_replaced_wholesale():
    current = {"coreFeatures": ["chat"]}
    extracted = {"coreFeatures": ["chat", "roadmap view"]}
    assert merge_brief(current, extracted)["coreFeatures"] == ["chat", "roadmap view"]


def test_opening_message_varies_by_purpose():
    hobby = opening_message("hobby")
    startup = opening_message("startup")
    learning = opening_message("learning")
    assert len({hobby, startup, learning}) == 3
    assert "hobby" in hobby.lower()
    assert "learning" in learning.lower()


def test_opening_message_unknown_purpose_falls_back_to_default():
    assert opening_message(None) == opening_message("startup")
    assert opening_message("something-unrecognized") == opening_message("startup")


def test_system_prompt_branches_by_purpose():
    hobby_prompt = _system_prompt("hobby")
    startup_prompt = _system_prompt("startup")
    learning_prompt = _system_prompt("learning")
    assert "HOBBY" in hobby_prompt and "over-scoping" in hobby_prompt
    assert "STARTUP" in startup_prompt and "MVP" in startup_prompt
    assert "LEARNING" in learning_prompt and "skill" in learning_prompt.lower()
    # No purpose set → base prompt only, no purpose-specific claims leak in.
    base_prompt = _system_prompt(None)
    assert "HOBBY" not in base_prompt and "STARTUP" not in base_prompt


def test_missing_fields_tracks_required_only():
    assert "projectName" in missing_fields(None)
    full = {
        "projectName": "X", "problemStatement": "Y", "targetAudience": "Z",
        "coreFeatures": ["a"], "scope": "MVP", "timeline": "3 months",
    }
    assert missing_fields(full) == []
    assert "openQuestions" not in missing_fields({})


@pytest.mark.asyncio
async def test_resolve_api_key_prefers_byok(tmp_db):
    from src.database import get_db

    await _seed_org_and_team(anthropic_key="sk-byok")
    async for db in app.dependency_overrides[get_db]():
        with patch("src.services.idea_interview.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-platform"
            key = await resolve_api_key(ORG, db)
        assert key == "sk-byok"
        break


@pytest.mark.asyncio
async def test_resolve_api_key_falls_back_to_platform(tmp_db):
    from src.database import get_db

    await _seed_org_and_team(anthropic_key=None)
    async for db in app.dependency_overrides[get_db]():
        with patch("src.services.idea_interview.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-platform"
            key = await resolve_api_key(ORG, db)
        assert key == "sk-platform"
        break


@pytest.mark.asyncio
async def test_resolve_api_key_402_when_no_key(tmp_db):
    from fastapi import HTTPException
    from src.database import get_db

    await _seed_org_and_team(anthropic_key=None)
    async for db in app.dependency_overrides[get_db]():
        with patch("src.services.idea_interview.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            with pytest.raises(HTTPException) as exc:
                await resolve_api_key(ORG, db)
        assert exc.value.status_code == 402
        break


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_start_idempotent_with_opening_message(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            first = (await _start_chat(client)).json()
            second = (await _start_chat(client)).json()

    assert first["status"] == "in_progress"
    assert len(first["messages"]) == 1
    assert first["messages"][0]["role"] == "assistant"
    assert second["sessionId"] == first["sessionId"]
    assert len(second["messages"]) == 1


@pytest.mark.asyncio
async def test_chat_get_not_started(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/chat", headers=AUTH)
    assert resp.json()["status"] == "not_started"


@pytest.mark.asyncio
async def test_chat_message_requires_session(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "hi"}, headers=AUTH
            )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "chat_not_started"


@pytest.mark.asyncio
async def test_chat_message_402_without_any_key(tmp_db):
    await _seed_org_and_team(anthropic_key=None)
    with (
        _patch_clerk(),
        patch("src.services.idea_interview.settings") as mock_settings,
    ):
        mock_settings.anthropic_api_key = ""
        async with _client() as client:
            await _start_chat(client)
            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "hi"}, headers=AUTH
            )
    assert resp.status_code == 402


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    import json as _json

    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        event = next(l[len("event: "):] for l in lines if l.startswith("event: "))
        data = next(l[len("data: "):] for l in lines if l.startswith("data: "))
        events.append((event, _json.loads(data)))
    return events


@pytest.mark.asyncio
async def test_chat_message_streams_tokens_brief_and_done(tmp_db):
    await _seed_org_and_team(anthropic_key="sk-byok")
    fake = _fake_anthropic(
        reply_chunks=["What problem ", "does it solve?"],
        extraction_payload={
            "projectName": "Roadmapper",
            "problemStatement": None,
            "coreFeatures": ["chat onboarding"],
            "isComplete": False,
        },
    )
    with (
        _patch_clerk(),
        patch("src.services.idea_interview.anthropic.AsyncAnthropic", return_value=fake),
    ):
        async with _client() as client:
            await _start_chat(client)
            resp = await client.post(
                "/api/onboarding/v2/chat/message",
                json={"content": "I want to build a roadmap AI"},
                headers=AUTH,
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    kinds = [e for e, _ in events]
    assert kinds == ["token", "token", "brief", "done"]
    assert events[0][1]["text"] == "What problem "
    brief = events[2][1]
    assert brief["brief"]["projectName"] == "Roadmapper"
    assert brief["briefComplete"] is False
    assert "problemStatement" in brief["missingFields"]
    done = events[3][1]
    assert done["status"] == "in_progress"

    # Transcript persisted: opening + user + assistant.
    with _patch_clerk():
        async with _client() as client:
            chat = (await client.get("/api/onboarding/v2/chat", headers=AUTH)).json()
    assert [m["role"] for m in chat["messages"]] == ["assistant", "user", "assistant"]
    assert chat["messages"][2]["content"] == "What problem does it solve?"


@pytest.mark.asyncio
async def test_chat_completes_when_brief_complete(tmp_db):
    await _seed_org_and_team(anthropic_key="sk-byok")
    full_brief = {
        "projectName": "Roadmapper",
        "problemStatement": "planning is hard",
        "targetAudience": "founders",
        "coreFeatures": ["chat"],
        "scope": "MVP chat",
        "timeline": "3 months",
        "isComplete": True,
    }
    fake = _fake_anthropic(reply_chunks=["Summary. You're all set!"], extraction_payload=full_brief)
    with (
        _patch_clerk(),
        patch("src.services.idea_interview.anthropic.AsyncAnthropic", return_value=fake),
    ):
        async with _client() as client:
            await _start_chat(client)
            resp = await client.post(
                "/api/onboarding/v2/chat/message",
                json={"content": "here's everything about my idea..."},
                headers=AUTH,
            )
            events = _parse_sse(resp.text)
            assert events[-1][1]["status"] == "completed"

            # Session now completed → further messages rejected, state shows done.
            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "more"}, headers=AUTH
            )
            assert resp.status_code == 409
            assert resp.json()["detail"] == "chat_completed"

            state = (await client.get("/api/onboarding/v2/state", headers=AUTH)).json()
            assert state["ideaChat"]["status"] == "completed"
            assert state["ideaChat"]["briefComplete"] is True


@pytest.mark.asyncio
async def test_chat_user_override_complete(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            await _start_chat(client)
            resp = await client.post("/api/onboarding/v2/chat/complete", headers=AUTH)
            state = resp.json()
    assert state["ideaChat"]["status"] == "completed"
    assert state["ideaChat"]["briefComplete"] is False


@pytest.mark.asyncio
async def test_chat_message_cap(tmp_db):
    await _seed_org_and_team(anthropic_key="sk-byok")

    from src.database import get_db
    from src.models.onboarding_session import OnboardingMessage, OnboardingSession
    from sqlalchemy import select

    with _patch_clerk():
        async with _client() as client:
            await _start_chat(client)

            async for db in app.dependency_overrides[get_db]():
                session = await db.scalar(select(OnboardingSession))
                for i in range(40):
                    db.add(OnboardingMessage(
                        session_id=session.id, role="user", content=f"m{i}", seq=i + 1
                    ))
                await db.commit()
                break

            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "one more"}, headers=AUTH
            )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "message_cap_reached"


@pytest.mark.asyncio
async def test_chat_stream_error_event_on_failure(tmp_db):
    await _seed_org_and_team(anthropic_key="sk-byok")

    with (
        _patch_clerk(),
        patch(
            "src.routers.onboarding_v2.idea_interview.run_interview_turn",
            new=AsyncMock(side_effect=RuntimeError("Anthropic API error: boom")),
        ),
    ):
        async with _client() as client:
            await _start_chat(client)
            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "hi"}, headers=AUTH
            )
    events = _parse_sse(resp.text)
    assert events[-1][0] == "error"
    assert "boom" in events[-1][1]["message"]
