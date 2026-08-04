"""
Per-request correlation and access logging.

Every request gets an id (honouring an inbound `X-Request-ID` so a trace can
survive a proxy hop) which is bound into a ContextVar, stamped onto every log
record emitted while handling that request, and echoed back on the response.
When a user reports "it broke", the id on their failed response is enough to
pull the whole server-side story out of the logs.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from src.logging_config import org_id_var, request_id_var, user_id_var

logger = logging.getLogger("src.access")

# Health checks fire constantly (Railway polls /health per railway.toml) and
# would bury real traffic. Still logged if they fail — see below.
_QUIET_PATHS = {"/health", "/favicon.ico"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, slow_request_ms: int = 3000) -> None:
        super().__init__(app)
        self.slow_request_ms = slow_request_ms

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        rid_token = request_id_var.set(request_id)
        user_token = user_id_var.set(None)
        org_token = org_id_var.set(None)
        request.state.request_id = request_id

        start = time.perf_counter()
        path = request.url.path
        # The ContextVar resets must happen *after* the access log below,
        # otherwise that line is emitted with no request_id and can't be
        # correlated with the handler's own logs.
        try:
            try:
                response = await call_next(request)
            except Exception:
                # main.py's handler turns this into a 500 body; we log here
                # because only the middleware knows the timing and the client
                # context. The flag tells that handler this failure is already
                # on the record, so one 500 never yields two stack traces.
                request.state.exception_logged = True
                duration_ms = round((time.perf_counter() - start) * 1000, 1)
                logger.exception(
                    "request failed %s %s",
                    request.method,
                    path,
                    extra={
                        "http_method": request.method,
                        "http_path": path,
                        "http_status": 500,
                        "duration_ms": duration_ms,
                        "client_ip": _client_ip(request),
                    },
                )
                raise

            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            response.headers["X-Request-ID"] = request_id

            status = response.status_code
            # Quiet paths stay quiet only while they're healthy.
            if path in _QUIET_PATHS and status < 400:
                return response

            if status >= 500:
                level = logging.ERROR
            elif status >= 400:
                level = logging.WARNING
            elif duration_ms >= self.slow_request_ms:
                level = logging.WARNING
            else:
                level = logging.INFO

            logger.log(
                level,
                "%s %s -> %s (%sms)",
                request.method,
                path,
                status,
                duration_ms,
                extra={
                    "http_method": request.method,
                    "http_path": path,
                    "http_status": status,
                    "duration_ms": duration_ms,
                    "client_ip": _client_ip(request),
                    "slow": duration_ms >= self.slow_request_ms,
                },
            )
            return response
        finally:
            request_id_var.reset(rid_token)
            user_id_var.reset(user_token)
            org_id_var.reset(org_token)


def _client_ip(request: Request) -> str | None:
    """Prefer the left-most X-Forwarded-For hop (Railway terminates TLS upstream)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
