"""
GitHub App webhook receiver — one app-level webhook URL (configured once in
the GitHub App's own settings — infra, not code) delivers `push` and
`pull_request` events for every installed repo across every org. No user
auth (GitHub can't present ours); instead we verify `X-Hub-Signature-256`
via HMAC-SHA256 against the single app-level `github_app_webhook_secret`.

Gated behind the `experimental.github_autocomplete` feature flag, same
posture as artifact_import.py: 404 (not 403) while off, so the endpoint is
invisible rather than just refused.

POST /api/webhooks/github
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.integrations.github.events import process_github_event
from src.integrations.github.webhook_verify import verify_signature
from src.models.github_connection import GithubConnection

logger = logging.getLogger(__name__)

_HANDLED_EVENTS = {"push", "pull_request"}


def _require_github_autocomplete_enabled() -> None:
    if not settings.is_feature_enabled("experimental.github_autocomplete"):
        raise HTTPException(status_code=404, detail="not_found")


router = APIRouter(
    tags=["github-webhooks"],
    dependencies=[Depends(_require_github_autocomplete_enabled)],
)


@router.post("/api/webhooks/github")
async def receive_github_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    if not verify_signature(settings.github_app_webhook_secret, body, signature):
        raise HTTPException(status_code=401, detail="invalid_signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_payload")

    event_type = request.headers.get("x-github-event", "")
    if event_type not in _HANDLED_EVENTS:
        # GitHub sends plenty of event types we don't care about (issues,
        # stars, the initial "ping" on webhook setup, ...) — ack and drop.
        return {"ok": True, "ignored": True}

    installation_id = str((payload.get("installation") or {}).get("id") or "")
    if not installation_id:
        return {"ok": True, "ignored": True}

    connection = await db.scalar(
        select(GithubConnection).where(
            GithubConnection.installation_id == installation_id,
            GithubConnection.is_active == True,  # noqa: E712
        )
    )
    if connection is None:
        # Installation not (or no longer) connected to any org — nothing to do.
        return {"ok": True, "ignored": True}

    # Hand off and return fast, well under GitHub's ~10s webhook timeout.
    process_github_event.delay(str(connection.organization_id), event_type, payload)
    return {"ok": True}
