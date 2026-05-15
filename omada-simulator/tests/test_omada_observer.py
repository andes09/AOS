"""Tests for src/omada_observer.py — header wiring and defensive _request."""

from __future__ import annotations

import httpx

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


def test_request_sends_no_auth_header(monkeypatch):
    """The simulator runs against a local API with clerk_auth=false, so
    no Authorization or simulator-key header should be sent."""
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("Authorization", "")
        seen["sim_key"] = req.headers.get("X-Simulator-Key", "")
        return httpx.Response(200, json={"ok": True})

    _install_mock_transport(monkeypatch, handler)

    with OmadaObserver("http://localhost:8000") as obs:
        assert obs._request("GET", "/api/me") == {"ok": True}

    assert seen["auth"] == ""
    assert seen["sim_key"] == ""


def test_non_2xx_returns_none_and_does_not_raise(monkeypatch):
    """A 500 (or any >=400) is logged and returned as None — the simulator
    never raises so broken endpoints surface in the bug report."""
    def handler(req):
        return httpx.Response(500, text="boom")

    _install_mock_transport(monkeypatch, handler)

    with OmadaObserver("http://localhost:8000") as obs:
        assert obs._request("GET", "/api/me") is None


def test_401_returns_none_without_retry(monkeypatch):
    """A 401 means clerk_auth is enabled on the target API. No retry path
    exists — the call is logged and surfaced as a bug."""
    calls: list[str] = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(401, text="unauthorized")

    _install_mock_transport(monkeypatch, handler)

    with OmadaObserver("http://localhost:8000") as obs:
        assert obs._request("GET", "/api/me") is None

    assert calls == ["/api/me"]  # exactly one attempt, no retry
