"""
Central logging setup for the API and the Celery worker.

Why this module exists: nothing in the app ever configured the `logging` root
logger. Uvicorn's default dictConfig only configures the `uvicorn*` loggers, so
every `logging.getLogger("src.…")` record propagated to a root logger with **no
handlers** and an implicit WARNING level. Two consequences, both confirmed by
running uvicorn's LOGGING_CONFIG and emitting records against it:

  * every `logger.info(...)` in the codebase was dropped on the floor;
  * warnings/errors fell through to `logging.lastResort`, which writes the bare
    message to stderr — no timestamp, no logger name, no level, no traceback
    formatting. Unusable for working out what broke in Railway logs.

`setup_logging()` installs a single stdout handler on the root logger so app
records are actually emitted, formatted, and correlatable.
"""

from __future__ import annotations

import contextvars
import datetime as _dt
import json
import logging
import os
import sys
import traceback

# ─── Request-scoped correlation ────────────────────────────────────────────────
# Set by RequestContextMiddleware (API) and by the task wrappers in worker.py.
# ContextVars are the right primitive here: they're per-task under asyncio, so
# concurrent requests never read each other's ids.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)
org_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("org_id", default=None)

# Attributes present on every LogRecord; anything else a caller passes via
# `extra=` is treated as structured context and merged into the payload.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"asctime", "message", "taskName"}

# Injected onto every record by ContextFilter; rendered explicitly, never as
# part of the generic `extra=` merge.
_CONTEXT_KEYS = frozenset({"request_id", "user_id", "org_id"})


class ContextFilter(logging.Filter):
    """Attach the current request/user/org ids to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user_id = user_id_var.get()
        record.org_id = org_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line — what Railway's log search can actually index."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": _dt.datetime.fromtimestamp(record.created, _dt.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "user_id", "org_id"):
            value = getattr(record, key, None)
            if value:
                payload[key] = value

        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            payload["error"] = {
                "type": getattr(exc_type, "__name__", str(exc_type)),
                "message": str(exc_value),
                "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            }

        # Merge caller-supplied `extra={...}` so structured fields survive.
        # `_CONTEXT_KEYS` are excluded because they're handled above and would
        # otherwise reappear as explicit nulls on every single line.
        for key, value in record.__dict__.items():
            if (
                key not in _RESERVED
                and key not in _CONTEXT_KEYS
                and key not in payload
                and not key.startswith("_")
            ):
                payload[key] = value

        return json.dumps(payload, default=str)


class HumanFormatter(logging.Formatter):
    """Readable single line for local dev, with the correlation id when set."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-8s %(name)s%(_ctx)s | %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", None)
        record._ctx = f" [{rid[:8]}]" if rid else ""
        line = super().format(record)
        # Append structured `extra={...}` fields; without this they're invisible
        # in dev and you end up debugging against a different payload than prod.
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_") and k not in _CONTEXT_KEYS
        }
        if extras:
            line += " " + " ".join(f"{k}={v!r}" for k, v in extras.items())
        return line


# Third-party loggers that are pure noise at INFO and drown out real signal.
_NOISY = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    "asyncio": logging.WARNING,
    "multipart": logging.WARNING,
    "sqlalchemy.engine.Engine": logging.WARNING,
}

_configured = False


def setup_logging(*, force: bool = False) -> None:
    """
    Install the root stdout handler. Idempotent — safe to call from both the
    API process and the Celery worker, and safe if a reloader re-imports us.

    Level comes from `LOG_LEVEL` (default INFO). Format is JSON in production
    and human-readable elsewhere, overridable with `LOG_FORMAT=json|human`.
    """
    global _configured
    if _configured and not force:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    environment = os.getenv("ENVIRONMENT", "local")
    fmt = os.getenv("LOG_FORMAT", "json" if environment == "production" else "human").lower()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else HumanFormatter())
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    # Drop handlers we installed on a previous call; leave any others alone.
    for existing in list(root.handlers):
        if getattr(existing, "_omada_handler", False):
            root.removeHandler(existing)
    handler._omada_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn installs its own handlers on these; let them propagate to ours
    # instead so every line shares one format and one destination.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True

    for name, noisy_level in _NOISY.items():
        logging.getLogger(name).setLevel(max(noisy_level, level))

    _configured = True
    logging.getLogger(__name__).info(
        "logging configured", extra={"log_level": level_name, "log_format": fmt, "environment": environment}
    )
