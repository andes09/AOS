"""Tests for src/omada_observer.py — specifically the 401 user-facing message."""

from __future__ import annotations

import httpx
import pytest

from src.omada_observer import OmadaObserver


def _install_mock_transport(monkeypatch, handler) -> None:
    """Force OmadaObserver to use httpx.MockTransport without touching its API.

    OmadaObserver instantiates httpx.Client(...) in __init__ with no
    `transport` kwarg, so we monkeypatch the class to inject one.
    """
    real_client_cls = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("src.omada_observer.httpx.Client", factory)


def test_401_prints_token_guidance_once(monkeypatch, capsys):
    """Every endpoint will 401 once the token expires. We should print the
    'get a fresh token' guidance the FIRST time we see a 401, and stay
    quiet on subsequent ones so the run isn't flooded with the same lines.
    """
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    _install_mock_transport(monkeypatch, handler)

    with OmadaObserver("http://localhost:8000", "stale-token") as obs:
        assert obs._request("GET", "/api/me") is None
        assert obs._request("GET", "/api/features") is None
        assert obs._request("GET", "/api/teams") is None

    out = capsys.readouterr().out
    # Exactly one "Token expired" line, regardless of how many 401s flew.
    assert out.count("Token expired. Re-run with a fresh --token value.") == 1
    assert "window.Clerk.session.getToken()" in out


def test_non_401_errors_do_not_emit_token_guidance(monkeypatch, capsys):
    """A 500 / network error shouldn't tell the user to refresh their token."""
    def handler(req):
        return httpx.Response(500, text="boom")

    _install_mock_transport(monkeypatch, handler)

    with OmadaObserver("http://localhost:8000", "fresh-token") as obs:
        assert obs._request("GET", "/api/me") is None

    out = capsys.readouterr().out
    assert "Token expired" not in out
