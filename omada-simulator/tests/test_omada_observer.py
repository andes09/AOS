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


def test_request_sends_x_simulator_key_header(monkeypatch):
    """Every Omada call must carry X-Simulator-Key with the configured value."""
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["key"] = req.headers.get("X-Simulator-Key", "")
        seen["auth"] = req.headers.get("Authorization", "")
        return httpx.Response(200, json={"ok": True})

    _install_mock_transport(monkeypatch, handler)

    with OmadaObserver("http://localhost:8000", "sim-key-abc") as obs:
        assert obs._request("GET", "/api/me") == {"ok": True}

    assert seen["key"] == "sim-key-abc"
    assert seen["auth"] == ""  # no Bearer token any more


def test_non_2xx_returns_none_and_does_not_raise(monkeypatch):
    """A 500 (or any >=400) is logged and returned as None — the simulator
    never raises so broken endpoints surface in the bug report."""
    def handler(req):
        return httpx.Response(500, text="boom")

    _install_mock_transport(monkeypatch, handler)

    with OmadaObserver("http://localhost:8000", "sim-key") as obs:
        assert obs._request("GET", "/api/me") is None


def test_401_returns_none_without_retry(monkeypatch):
    """With the static key, 401 just means the key is wrong — no refresh path."""
    calls: list[str] = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(401, text="unauthorized")

    _install_mock_transport(monkeypatch, handler)

    with OmadaObserver("http://localhost:8000", "sim-key") as obs:
        assert obs._request("GET", "/api/me") is None

    assert calls == ["/api/me"]  # exactly one attempt, no retry
