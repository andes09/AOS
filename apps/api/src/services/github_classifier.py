"""
The third and last matching tier: ask Groq about the commits neither the exact
`short_id` path nor the token heuristics could place.

Tier ordering (see integrations/github/events.py's module docstring) exists to
keep this one cheap and rare. Everything an identifier or a token overlap can
resolve is already resolved by the time a row reaches here, so this runs over
the genuinely ambiguous residue — a commit like "wire up the new provider" that
means something specific to the roadmap but shares no vocabulary with it.

Three properties this deliberately has:

  - **Batched, not per-event.** One call classifies up to `_BATCH_SIZE` events
    against the project's whole task list. Per-event calls would multiply cost
    by two orders of magnitude for a worse result, since the model can't see
    that two commits are obviously the same piece of work.
  - **Idempotent by `classified_at`.** A row is looked at once. The sweep runs
    every 6h and mostly re-sees rows it has already paid for; the cursor stops
    it re-billing them.
  - **Evidence only.** Like the heuristic tier, an LLM match sets
    `matched_task_id` + `match_method='llm'` + a confidence, and never touches
    `Task.status`. Only an exact `short_id` may complete a task.

When no Groq key is configured this logs once and returns — a background job
must not raise `HTTPException` the way `idea_interview.resolve_api_key` does
for a request path.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.github_activity_event import GithubActivityEvent, MatchMethod
from src.models.milestone import Milestone
from src.models.project import Project
from src.models.task import Task, TaskStatus
from src.models.team import Team
from src.services.cost_tracker import record_generation_cost
from src.worker import celery_app

logger = logging.getLogger(__name__)

# How many unclassified events one Groq call covers. Sized so the prompt (this
# many commit messages plus the task list) stays well inside the context window
# with room for the tool-call response.
_BATCH_SIZE = 40
# Don't spend tokens re-litigating ancient history — the drift service only
# looks at a recent window anyway, so anything older is dead weight.
_MAX_AGE_DAYS = 30
# Below this the model is guessing, and a guess recorded as a match would
# understate unplanned work — the exact failure this whole tier exists to
# avoid. Unconfident rows stay 'unmatched'.
_MIN_CONFIDENCE = 0.6

_SYSTEM_PROMPT = """You map git activity onto a software project's plan.

You are given a numbered list of TASKS from the project's roadmap, and a
numbered list of EVENTS (commit messages, PR titles, branch names) that could
not be matched to a task automatically.

For each event, decide which task — if any — that work belongs to.

Rules:
- Most events genuinely belong to no planned task. Chores, dependency bumps,
  formatting, CI fiddling, config, and work on things the roadmap never
  mentions are all UNPLANNED. Say so by returning taskIndex = null.
- Do not stretch to find a match. "Related to the same general area" is not a
  match; the event must plausibly be work *on that specific task*.
- confidence is your honest probability the match is right, 0.0 to 1.0.
- Return exactly one entry per event, in the order given."""

_CLASSIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_events",
        "description": "Map each git event to a roadmap task, or to nothing.",
        "parameters": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "eventIndex": {"type": "integer", "description": "1-based index from the EVENTS list"},
                            "taskIndex": {
                                "type": ["integer", "null"],
                                "description": "1-based index from the TASKS list, or null when the work is unplanned",
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": ["eventIndex", "taskIndex", "confidence"],
                    },
                }
            },
            "required": ["results"],
        },
    },
}


def _prompt(tasks: list[Task], events: list[GithubActivityEvent]) -> str:
    task_lines = "\n".join(
        f"{i}. {t.title}" + (f" — {t.description[:200]}" if t.description else "")
        for i, t in enumerate(tasks, start=1)
    )
    event_lines = "\n".join(
        f"{i}. [{e.event_type}]"
        + (f" branch={e.branch}" if e.branch else "")
        + f" {(e.title_or_message or '').strip()[:300]}"
        for i, e in enumerate(events, start=1)
    )
    return f"TASKS:\n{task_lines}\n\nEVENTS:\n{event_lines}"


async def _open_tasks(db, organization_id) -> list[Task]:
    return list(
        await db.scalars(
            select(Task)
            .join(Milestone, Task.milestone_id == Milestone.id)
            .join(Project, Milestone.project_id == Project.id)
            .join(Team, Project.team_id == Team.id)
            .where(Team.organization_id == organization_id, Task.status != TaskStatus.DONE.value)
            .order_by(Task.created_at)
        )
    )


async def _unclassified_events(db, organization_id) -> list[GithubActivityEvent]:
    cutoff = datetime.utcnow() - timedelta(days=_MAX_AGE_DAYS)
    return list(
        await db.scalars(
            select(GithubActivityEvent)
            .where(
                GithubActivityEvent.organization_id == organization_id,
                GithubActivityEvent.match_method == MatchMethod.UNMATCHED,
                GithubActivityEvent.classified_at.is_(None),
                GithubActivityEvent.occurred_at >= cutoff,
            )
            .order_by(GithubActivityEvent.occurred_at.desc())
            .limit(_BATCH_SIZE)
        )
    )


async def classify_unmatched_events_async(organization_id, db) -> int:
    """Classify one batch. Returns how many events were newly linked to a task.

    Every event in the batch gets `classified_at` stamped whether or not it
    matched — an event the model deliberately called unplanned is a *resolved*
    question, and re-asking it every six hours would be the main cost of this
    feature.
    """
    if not settings.groq_api_key:
        logger.info("github classifier skipped — no GROQ_API_KEY configured")
        return 0

    events = await _unclassified_events(db, organization_id)
    if not events:
        return 0

    tasks = await _open_tasks(db, organization_id)
    if not tasks:
        # Nothing to match against. Still stamp them so an org with no roadmap
        # doesn't get re-scanned forever.
        for event in events:
            event.classified_at = datetime.utcnow()
        await db.commit()
        return 0

    # Imported here rather than at module scope: roadmap_generator imports the
    # Celery app too, and a top-level import in both directions is how this
    # package's existing router<->events cycle started.
    from src.services.roadmap_generator import _call_planner

    try:
        data, usage = await _call_planner(
            settings.groq_api_key, _SYSTEM_PROMPT, _prompt(tasks, events), _CLASSIFY_TOOL
        )
    except Exception:
        # A classifier failure must not fail the reconciliation sweep that
        # called it — the rows stay unclassified and get another turn next
        # sweep, which is exactly the desired degradation.
        logger.warning("github classifier call failed for org %s", organization_id, exc_info=True)
        return 0

    now = datetime.utcnow()
    matched = 0
    for entry in data.get("results") or []:
        event = _lookup(events, entry.get("eventIndex"))
        if event is None:
            continue
        event.classified_at = now

        task = _lookup(tasks, entry.get("taskIndex"))
        confidence = entry.get("confidence")
        if task is None or not isinstance(confidence, (int, float)) or confidence < _MIN_CONFIDENCE:
            continue

        event.matched_task_id = task.id
        event.match_method = MatchMethod.LLM
        event.match_confidence = round(float(confidence), 4)
        matched += 1

    # Anything the model silently omitted still gets stamped, or it would be
    # retried forever at full cost.
    for event in events:
        if event.classified_at is None:
            event.classified_at = now

    await db.commit()

    await record_generation_cost(
        "github_classify_events",
        usage,
        provider="groq",
        org_id=organization_id,
        model=settings.groq_model,
        batch_size=len(events),
        matched=matched,
    )

    logger.info(
        "github classifier processed org=%s events=%s matched=%s",
        organization_id, len(events), matched,
    )
    return matched


def _lookup(items: list, index) -> object | None:
    """1-based index into `items`, tolerant of whatever the model returns."""
    if not isinstance(index, int) or index < 1 or index > len(items):
        return None
    return items[index - 1]


@celery_app.task(bind=True, max_retries=2)
def classify_unmatched_events(self, organization_id: str):
    """Celery entry point — same sync/async bridge shape as
    `integrations.github.events.process_github_event`."""
    async def _run() -> int:
        async with AsyncSessionLocal() as db:
            try:
                return await classify_unmatched_events_async(organization_id, db)
            except Exception:
                await db.rollback()
                raise

    try:
        return asyncio.run(_run())
    except Exception as exc:  # pragma: no cover — retry semantics, not unit-tested
        logger.exception("classify_unmatched_events failed for org %s", organization_id)
        raise self.retry(exc=exc, countdown=min(60 * (2 ** self.request.retries), 900))
