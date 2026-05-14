"""Tests for src/clerk_auth.py — frontend URL decoding, sign-in, token refresh."""

from __future__ import annotations

import time

import httpx
import pytest

from src.clerk_auth import (
    CLERK_TOKEN_TTL_SECONDS,
    ClerkAuth,
    ClerkAuthError,
    derive_frontend_api_url,
)


# ---------- derive_frontend_api_url ----------

def test_derive_frontend_api_url_decodes_pk_test():
    # Same value used by apps/web/.env — must decode to the dev host.
    url = derive_frontend_api_url(
        "pk_test_c2luY2VyZS1yaGluby0wLmNsZXJrLmFjY291bnRzLmRldiQ"
    )
    assert url == "https://sincere-rhino-0.clerk.accounts.dev"


def test_derive_frontend_api_url_rejects_unknown_prefix():
    with pytest.raises(ValueError, match="pk_test_ or pk_live_"):
        derive_frontend_api_url("sk_test_whatever")


def test_derive_frontend_api_url_rejects_garbage_base64():
    with pytest.raises(ValueError):
        derive_frontend_api_url("pk_test_!!!not_base64!!!")


# ---------- ClerkAuth.sign_in ----------

_SIGN_IN_PATH = "/v1/client/sign_ins"
_TOKENS_PATH_TPL = "/v1/client/sessions/{sid}/tokens"


def _ok_signin_body(session_id: str = "sess_abc", jwt: str = "jwt-initial") -> dict:
    return {
        "response": {
            "status": "complete",
            "created_session_id": session_id,
        },
        "client": {
            "sessions": [
                {
                    "id": session_id,
                    "last_active_token": {"jwt": jwt},
                }
            ],
        },
    }


def test_sign_in_succeeds_and_seeds_token():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["path"] = req.url.path
        captured["body"] = req.read().decode()
        return httpx.Response(200, json=_ok_signin_body(jwt="jwt-initial"))

    auth = ClerkAuth.sign_in(
        "https://example.clerk.accounts.dev",
        email="sim@example.com",
        password="hunter2",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert captured["method"] == "POST"
        assert captured["path"] == _SIGN_IN_PATH
        # Form-encoded body with all three required fields.
        assert "strategy=password" in captured["body"]
        assert "identifier=sim%40example.com" in captured["body"]
        assert "password=hunter2" in captured["body"]
        # First get_token() returns the seeded JWT without another network call.
        assert auth.get_token() == "jwt-initial"
    finally:
        auth.close()


def test_sign_in_raises_on_non_2xx():
    def handler(req):
        return httpx.Response(400, text='{"errors":[{"message":"bad password"}]}')

    with pytest.raises(ClerkAuthError, match="sign-in failed"):
        ClerkAuth.sign_in(
            "https://example.clerk.accounts.dev",
            email="sim@example.com",
            password="wrong",
            transport=httpx.MockTransport(handler),
        )


def test_sign_in_raises_when_status_not_complete():
    """Clerk returns status='needs_first_factor' / 'needs_second_factor' when
    MFA is in play. The simulator can't satisfy that interactively, so we
    bail with a clear message rather than hanging."""
    def handler(req):
        body = {
            "response": {
                "status": "needs_second_factor",
                "created_session_id": None,
            },
            "client": {"sessions": []},
        }
        return httpx.Response(200, json=body)

    with pytest.raises(ClerkAuthError, match="did not complete"):
        ClerkAuth.sign_in(
            "https://example.clerk.accounts.dev",
            email="sim@example.com",
            password="hunter2",
            transport=httpx.MockTransport(handler),
        )


def test_sign_in_raises_on_network_error():
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(ClerkAuthError, match="Could not reach Clerk"):
        ClerkAuth.sign_in(
            "https://example.clerk.accounts.dev",
            email="sim@example.com",
            password="hunter2",
            transport=httpx.MockTransport(handler),
        )


# ---------- token refresh ----------

def test_get_token_refreshes_when_expired(monkeypatch):
    """After 50+ seconds (60s TTL with 10s margin), the next get_token()
    must hit the /sessions/<id>/tokens endpoint and return the new JWT."""
    session_id = "sess_refresh"
    call_count = {"refresh": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == _SIGN_IN_PATH:
            return httpx.Response(200, json=_ok_signin_body(session_id, "jwt-1"))
        if req.url.path == _TOKENS_PATH_TPL.format(sid=session_id):
            call_count["refresh"] += 1
            return httpx.Response(200, json={"jwt": f"jwt-{call_count['refresh'] + 1}"})
        return httpx.Response(404, text="unexpected path")

    auth = ClerkAuth.sign_in(
        "https://example.clerk.accounts.dev",
        email="sim@example.com",
        password="hunter2",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert auth.get_token() == "jwt-1"

        # Fast-forward time past the refresh margin without sleeping.
        fake_now = [time.monotonic() + CLERK_TOKEN_TTL_SECONDS]
        monkeypatch.setattr("src.clerk_auth.time.monotonic", lambda: fake_now[0])

        assert auth.get_token() == "jwt-2"
        assert call_count["refresh"] == 1
        # And we should not re-refresh until the new token also expires.
        assert auth.get_token() == "jwt-2"
        assert call_count["refresh"] == 1
    finally:
        auth.close()


def test_refresh_raises_on_revoked_session(monkeypatch):
    session_id = "sess_revoked"

    def handler(req):
        if req.url.path == _SIGN_IN_PATH:
            return httpx.Response(200, json=_ok_signin_body(session_id, "jwt-1"))
        return httpx.Response(404, text="session not found")

    auth = ClerkAuth.sign_in(
        "https://example.clerk.accounts.dev",
        email="sim@example.com",
        password="hunter2",
        transport=httpx.MockTransport(handler),
    )
    try:
        # Force the refresh path.
        fake_now = [time.monotonic() + CLERK_TOKEN_TTL_SECONDS]
        monkeypatch.setattr("src.clerk_auth.time.monotonic", lambda: fake_now[0])

        with pytest.raises(ClerkAuthError, match="token refresh failed"):
            auth.get_token()
    finally:
        auth.close()
