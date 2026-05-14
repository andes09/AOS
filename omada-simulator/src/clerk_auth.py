"""Clerk Frontend-API sign-in with token auto-refresh.

The Omada API only accepts Clerk-issued JWTs, which expire 60 seconds after
issue. Pasting a session cookie into .env therefore lasts barely long enough
to read the error message. This module signs in with email + password at
startup and mints fresh JWTs from the session-tokens endpoint on demand, so
long-running simulator runs survive the TTL.
"""

from __future__ import annotations

import base64
import time
from typing import Any, Optional

import httpx


CLERK_TOKEN_TTL_SECONDS = 60
REFRESH_MARGIN_SECONDS = 10


def derive_frontend_api_url(publishable_key: str) -> str:
    """Decode pk_test_<base64> / pk_live_<base64> into the Frontend API URL.

    Clerk encodes the Frontend API host inside the publishable key, e.g.
    ``pk_test_c2luY2VyZS1yaGluby0wLmNsZXJrLmFjY291bnRzLmRldiQ`` decodes to
    ``sincere-rhino-0.clerk.accounts.dev$``. We strip the trailing ``$``
    sentinel and prepend ``https://``.
    """
    if not publishable_key.startswith(("pk_test_", "pk_live_")):
        raise ValueError(
            f"Invalid Clerk publishable key {publishable_key[:12]!r}... — "
            f"expected a pk_test_ or pk_live_ prefix."
        )
    encoded = publishable_key.split("_", 2)[-1]
    encoded += "=" * (-len(encoded) % 4)
    try:
        host = base64.b64decode(encoded).decode("utf-8").rstrip("$")
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"Could not decode publishable key: {e}")
    if not host:
        raise ValueError("Publishable key decoded to an empty host.")
    return f"https://{host}"


class ClerkAuthError(SystemExit):
    """SystemExit subclass so callers can catch auth failures explicitly."""


class ClerkAuth:
    """Holds a signed-in Clerk session and mints fresh JWTs on demand.

    Construct via ``ClerkAuth.sign_in(...)``. Call ``.get_token()`` from the
    HTTP layer immediately before each request — the cached JWT is reused
    until it nears its 60-second expiry, then transparently refreshed.
    """

    def __init__(
        self,
        frontend_api_url: str,
        session_id: str,
        client: httpx.Client,
    ) -> None:
        self._url = frontend_api_url.rstrip("/")
        self._session_id = session_id
        self._client = client
        self._token: Optional[str] = None
        self._token_fetched_at: float = 0.0

    @classmethod
    def sign_in(
        cls,
        frontend_api_url: str,
        email: str,
        password: str,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> "ClerkAuth":
        """Sign in via Clerk's ``POST /v1/client/sign_ins``.

        Raises ClerkAuthError (a SystemExit subclass) on any failure —
        network, non-2xx, missing session id, or a non-``complete`` status
        (which usually means MFA / email-verification is required, and the
        simulator has no way to satisfy that interactively).
        """
        base = frontend_api_url.rstrip("/")
        client_kwargs: dict[str, Any] = {
            "base_url": base,
            "timeout": 30.0,
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        client = httpx.Client(**client_kwargs)

        try:
            resp = client.post(
                "/v1/client/sign_ins",
                data={
                    "strategy": "password",
                    "identifier": email,
                    "password": password,
                },
            )
        except httpx.HTTPError as e:
            client.close()
            raise ClerkAuthError(
                f"Could not reach Clerk Frontend API at {base}: {e}"
            )

        if resp.status_code >= 400:
            body_preview = (resp.text or "")[:300]
            client.close()
            raise ClerkAuthError(
                f"Clerk sign-in failed ({resp.status_code}): {body_preview}. "
                f"Check OMADA_EMAIL / OMADA_PASSWORD in .env."
            )

        try:
            body = resp.json()
        except Exception as e:
            client.close()
            raise ClerkAuthError(f"Clerk sign-in returned non-JSON: {e}")

        response = body.get("response") or {}
        status = response.get("status")
        session_id = response.get("created_session_id")

        if status != "complete" or not session_id:
            client.close()
            raise ClerkAuthError(
                f"Clerk sign-in did not complete (status={status!r}). "
                f"MFA or email verification on this account would land here — "
                f"the simulator needs a service account without either. "
                f"Body: {str(body)[:300]}"
            )

        auth = cls(base, session_id, client)
        auth._seed_token_from_signin(body)
        return auth

    def _seed_token_from_signin(self, body: dict) -> None:
        """Pull the freshly-minted JWT out of the sign-in response.

        Clerk returns ``client.sessions[].last_active_token.jwt`` in the
        sign-in payload, which saves us a round-trip on the first request.
        Missing-token is fine — ``get_token()`` will fetch one lazily.
        """
        client_obj = body.get("client") or {}
        for session in client_obj.get("sessions") or []:
            if session.get("id") != self._session_id:
                continue
            lat = session.get("last_active_token") or {}
            jwt = lat.get("jwt")
            if jwt:
                self._token = jwt
                self._token_fetched_at = time.monotonic()
                return

    def get_token(self) -> str:
        """Return a JWT fresh enough to use for an outbound request.

        Clerk session JWTs live 60 s. We refresh proactively with a 10 s
        margin, so a token returned here will still be valid when it lands
        in the API's verifier even after a few seconds of in-flight time.
        """
        age = time.monotonic() - self._token_fetched_at
        if self._token and age < CLERK_TOKEN_TTL_SECONDS - REFRESH_MARGIN_SECONDS:
            return self._token
        return self._refresh()

    def _refresh(self) -> str:
        path = f"/v1/client/sessions/{self._session_id}/tokens"
        try:
            resp = self._client.post(path)
        except httpx.HTTPError as e:
            raise ClerkAuthError(f"Could not refresh Clerk session token: {e}")
        if resp.status_code >= 400:
            raise ClerkAuthError(
                f"Clerk token refresh failed ({resp.status_code}): "
                f"{(resp.text or '')[:300]}. Session may have been revoked."
            )
        try:
            body = resp.json()
        except Exception as e:
            raise ClerkAuthError(f"Clerk token refresh returned non-JSON: {e}")
        jwt = body.get("jwt")
        if not jwt:
            raise ClerkAuthError(
                f"Clerk token refresh missing jwt: {str(body)[:300]}"
            )
        self._token = jwt
        self._token_fetched_at = time.monotonic()
        return jwt

    @property
    def session_id(self) -> str:
        return self._session_id

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ClerkAuth":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
