import json
import uuid
from types import SimpleNamespace
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


async def _seed_org_and_team(clerk_org_id=ORG):
    from src.database import get_db
    from src.models.organization import Organization
    from src.models.team import Team

    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=uuid.uuid4(),
            clerk_org_id=clerk_org_id,
            name="Test Org",
            slug=clerk_org_id,
            use_managed_key=False,
        )
        db.add(org)
        await db.flush()
        db.add(Team(id=uuid.uuid4(), organization_id=org.id, name="Default"))
        await db.commit()
        return org.id


# ---------------------------------------------------------------------------
# Fake Groq (OpenAI-compatible) client: chat.completions.create() branches on
# `stream=True` (the conversational reply) vs. the forced-tool extraction
# call. Each entry in `turns` covers exactly one interview turn.
# ---------------------------------------------------------------------------

class _FakeStreamChunks:
    def __init__(self, tokens):
        self._tokens = tokens

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for t in self._tokens:
            yield SimpleNamespace(
                usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content=t))]
            )
        yield SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=80), choices=[]
        )


def _fake_groq(turns):
    """turns: list of (reply_tokens: list[str], extraction_payload: dict | None).

    extraction_payload=None simulates the model returning no tool call.
    """
    turns_iter = iter(turns)
    pending_extraction = {}

    async def create(**kwargs):
        if kwargs.get("stream"):
            reply_tokens, extraction_payload = next(turns_iter)
            pending_extraction["payload"] = extraction_payload
            return _FakeStreamChunks(reply_tokens)

        payload = pending_extraction.get("payload")
        tool_calls = (
            [SimpleNamespace(
                function=SimpleNamespace(name="update_project_brief", arguments=json.dumps(payload))
            )]
            if payload is not None
            else []
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=tool_calls))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        )

    fake_completions = SimpleNamespace(create=create)
    return SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))


def _patch_groq(fake):
    return patch("src.services.idea_interview.AsyncOpenAI", return_value=fake)


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


def test_system_prompt_asks_before_declaring_done():
    # The base prompt must ask for confirmation, not declare the interview over.
    base_prompt = _system_prompt(None)
    assert "anything else" in base_prompt.lower()
    assert "still waiting on their answer" in base_prompt.lower()
    assert "you can finish onboarding" not in base_prompt.lower()


def test_missing_fields_tracks_required_only():
    assert "projectName" in missing_fields(None)
    full = {
        "projectName": "X", "problemStatement": "Y", "targetAudience": "Z",
        "coreFeatures": ["a"], "scope": "MVP", "timeline": "3 months",
    }
    assert missing_fields(full) == []
    assert "openQuestions" not in missing_fields({})


@pytest.mark.asyncio
async def test_resolve_api_key_uses_platform_key(tmp_db):
    from src.database import get_db

    await _seed_org_and_team()
    async for db in app.dependency_overrides[get_db]():
        with patch("src.services.idea_interview.settings") as mock_settings:
            mock_settings.groq_api_key = "sk-platform"
            key = await resolve_api_key(ORG, db)
        assert key == "sk-platform"
        break


@pytest.mark.asyncio
async def test_resolve_api_key_402_when_no_key(tmp_db):
    from fastapi import HTTPException
    from src.database import get_db

    await _seed_org_and_team()
    async for db in app.dependency_overrides[get_db]():
        with patch("src.services.idea_interview.settings") as mock_settings:
            mock_settings.groq_api_key = ""
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
async def test_chat_message_402_without_key(tmp_db):
    await _seed_org_and_team()
    with (
        _patch_clerk(),
        patch("src.services.idea_interview.settings") as mock_settings,
    ):
        mock_settings.groq_api_key = ""
        async with _client() as client:
            await _start_chat(client)
            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "hi"}, headers=AUTH
            )
    assert resp.status_code == 402


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        event = next(l[len("event: "):] for l in lines if l.startswith("event: "))
        data = next(l[len("data: "):] for l in lines if l.startswith("data: "))
        events.append((event, json.loads(data)))
    return events


@pytest.mark.asyncio
async def test_chat_message_streams_tokens_brief_and_done(tmp_db):
    await _seed_org_and_team()
    fake = _fake_groq([
        (
            ["What problem ", "does it solve?"],
            {
                "projectName": "Roadmapper",
                "problemStatement": None,
                "coreFeatures": ["chat onboarding"],
                "isComplete": False,
            },
        ),
    ])
    with (
        _patch_clerk(),
        patch("src.services.idea_interview.settings") as mock_settings,
        _patch_groq(fake),
    ):
        mock_settings.groq_api_key = "gsk-platform"
        mock_settings.groq_base_url = "https://api.groq.com/openai/v1"
        mock_settings.groq_model = "llama-3.3-70b-versatile"
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
    assert brief["awaitingConfirmation"] is False
    assert "problemStatement" in brief["missingFields"]
    done = events[3][1]
    assert done["status"] == "in_progress"

    # Transcript persisted: opening + user + assistant.
    with _patch_clerk():
        async with _client() as client:
            chat = (await client.get("/api/onboarding/v2/chat", headers=AUTH)).json()
    assert [m["role"] for m in chat["messages"]] == ["assistant", "user", "assistant"]
    assert chat["messages"][2]["content"] == "What problem does it solve?"


_FULL_BRIEF = {
    "projectName": "Roadmapper",
    "problemStatement": "planning is hard",
    "targetAudience": "founders",
    "coreFeatures": ["chat"],
    "scope": "MVP chat",
    "timeline": "3 months",
}


@pytest.mark.asyncio
async def test_brief_complete_asks_for_confirmation_instead_of_finishing(tmp_db):
    """Filling the brief must NOT end the interview — it flips briefComplete,
    and the *next* turn (the one whose reply asks the closing question) flips
    awaitingConfirmation."""
    await _seed_org_and_team()
    fake = _fake_groq([
        (["Sounds great. What's the timeline?"], _FULL_BRIEF),
        (["Here's what I've got. ", "Anything else to add?"], _FULL_BRIEF),
    ])
    with (
        _patch_clerk(),
        patch("src.services.idea_interview.settings") as mock_settings,
        _patch_groq(fake),
    ):
        mock_settings.groq_api_key = "gsk-platform"
        mock_settings.groq_base_url = "https://api.groq.com/openai/v1"
        mock_settings.groq_model = "llama-3.3-70b-versatile"
        async with _client() as client:
            await _start_chat(client)
            resp = await client.post(
                "/api/onboarding/v2/chat/message",
                json={"content": "here's everything about my idea..."},
                headers=AUTH,
            )
            events = _parse_sse(resp.text)
            brief_event = next(d for e, d in events if e == "brief")
            done_event = next(d for e, d in events if e == "done")

            # The brief filled up on this turn, but the reply was written
            # against the *old* brief, so it can't have asked to wrap up yet.
            assert brief_event["briefComplete"] is True
            assert brief_event["awaitingConfirmation"] is False
            assert done_event["status"] == "in_progress"

            # Next turn: the prompt saw a complete brief, so its reply is the
            # closing question and the handshake arms.
            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "sounds right"}, headers=AUTH
            )
            events = _parse_sse(resp.text)
            assert next(d for e, d in events if e == "brief")["awaitingConfirmation"] is True
            # Not completed yet — still waiting on the founder's answer.
            assert next(d for e, d in events if e == "done")["status"] == "in_progress"

            # The session is still open: a follow-up message is accepted.
            state = (await client.get("/api/onboarding/v2/state", headers=AUTH)).json()
            assert state["ideaChat"]["status"] == "in_progress"
            assert state["ideaChat"]["briefComplete"] is True
            assert state["ideaChat"]["awaitingConfirmation"] is True


@pytest.mark.asyncio
async def test_confirmation_turn_completes_when_founder_says_no(tmp_db):
    await _seed_org_and_team()
    fake = _fake_groq([
        (["Tell me more."], _FULL_BRIEF),
        (["Anything else to add?"], _FULL_BRIEF),
        (["Great, you're all set!"], _FULL_BRIEF),
    ])
    with (
        _patch_clerk(),
        patch("src.services.idea_interview.settings") as mock_settings,
        _patch_groq(fake),
    ):
        mock_settings.groq_api_key = "gsk-platform"
        mock_settings.groq_base_url = "https://api.groq.com/openai/v1"
        mock_settings.groq_model = "llama-3.3-70b-versatile"
        async with _client() as client:
            await _start_chat(client)
            # Fills the brief, then draws the closing question.
            for msg in ("here's everything...", "yep, that's the shape of it"):
                await client.post(
                    "/api/onboarding/v2/chat/message", json={"content": msg}, headers=AUTH
                )

            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "no, that's everything"}, headers=AUTH
            )
            events = _parse_sse(resp.text)
            done_event = next(d for e, d in events if e == "done")
            assert done_event["status"] == "completed"

            # Session now completed → further messages rejected.
            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "more"}, headers=AUTH
            )
            assert resp.status_code == 409
            assert resp.json()["detail"] == "chat_completed"

            state = (await client.get("/api/onboarding/v2/state", headers=AUTH)).json()
            assert state["ideaChat"]["status"] == "completed"
            assert state["ideaChat"]["awaitingConfirmation"] is False


@pytest.mark.asyncio
async def test_confirmation_turn_completes_after_founder_adds_more(tmp_db):
    """If the founder answers 'yes' with more detail, the interview still
    ends this turn — the extra detail is merged into the brief first."""
    await _seed_org_and_team()
    fake = _fake_groq([
        (["Tell me more."], _FULL_BRIEF),
        (["Anything else to add?"], _FULL_BRIEF),
        (
            ["Got it, noted that. You're all set!"],
            {**_FULL_BRIEF, "techConstraints": ["must run on Postgres"]},
        ),
    ])
    with (
        _patch_clerk(),
        patch("src.services.idea_interview.settings") as mock_settings,
        _patch_groq(fake),
    ):
        mock_settings.groq_api_key = "gsk-platform"
        mock_settings.groq_base_url = "https://api.groq.com/openai/v1"
        mock_settings.groq_model = "llama-3.3-70b-versatile"
        async with _client() as client:
            await _start_chat(client)
            # Fills the brief, then draws the closing question.
            for msg in ("here's everything...", "yep, that's the shape of it"):
                await client.post(
                    "/api/onboarding/v2/chat/message", json={"content": msg}, headers=AUTH
                )

            resp = await client.post(
                "/api/onboarding/v2/chat/message",
                json={"content": "actually, it needs to run on Postgres"},
                headers=AUTH,
            )
            events = _parse_sse(resp.text)
            brief_event = next(d for e, d in events if e == "brief")
            done_event = next(d for e, d in events if e == "done")

            assert done_event["status"] == "completed"
            assert brief_event["brief"]["techConstraints"] == ["must run on Postgres"]

            state = (await client.get("/api/onboarding/v2/state", headers=AUTH)).json()
            assert state["ideaChat"]["status"] == "completed"
            assert state["ideaChat"]["brief"]["techConstraints"] == ["must run on Postgres"]


@pytest.mark.asyncio
async def test_handshake_does_not_depend_on_the_extraction_pass(tmp_db):
    """Regression: the interview used to arm (and therefore finish) only when
    the extraction pass judged the brief complete — a judgment made *after*
    the reply, and independent of what the reply actually asked. When they
    disagreed the founder got a sign-off message, no question to answer, and a
    session stuck at in_progress forever. The handshake now keys off the same
    brief snapshot the reply prompt saw, so an extraction that returns nothing
    at all can't stall it."""
    await _seed_org_and_team()
    fake = _fake_groq([
        (["Tell me more."], _FULL_BRIEF),
        (["Anything else to add?"], None),   # extraction returns no tool call
        (["All set!"], None),
    ])
    with (
        _patch_clerk(),
        patch("src.services.idea_interview.settings") as mock_settings,
        _patch_groq(fake),
    ):
        mock_settings.groq_api_key = "gsk-platform"
        mock_settings.groq_base_url = "https://api.groq.com/openai/v1"
        mock_settings.groq_model = "llama-3.3-70b-versatile"
        async with _client() as client:
            await _start_chat(client)
            for msg in ("here's everything...", "yep"):
                await client.post(
                    "/api/onboarding/v2/chat/message", json={"content": msg}, headers=AUTH
                )
            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "nope"}, headers=AUTH
            )
            assert next(d for e, d in _parse_sse(resp.text) if e == "done")["status"] == "completed"


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
    await _seed_org_and_team()

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
    await _seed_org_and_team()

    with (
        _patch_clerk(),
        patch("src.services.idea_interview.settings") as mock_settings,
        patch(
            "src.routers.onboarding_v2.idea_interview.run_interview_turn",
            new=AsyncMock(side_effect=RuntimeError("Groq API error: boom")),
        ),
    ):
        # Without this the request 402s in resolve_api_key before it ever
        # reaches the mocked turn, so the test only passed when a real
        # GROQ_API_KEY happened to be in the ambient env.
        mock_settings.groq_api_key = "gsk-platform"
        async with _client() as client:
            await _start_chat(client)
            resp = await client.post(
                "/api/onboarding/v2/chat/message", json={"content": "hi"}, headers=AUTH
            )
    events = _parse_sse(resp.text)
    assert events[-1][0] == "error"
    assert "boom" in events[-1][1]["message"]
