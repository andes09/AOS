"""
Roadmap generator — turns an onboarding project brief into a short-term,
day-by-day plan (project → milestones → tasks) for the calendar view.

One forced-tool Groq call (OpenAI-compatible) returns an ordered set of
milestones, each with small daily tasks tagged by weekday offset. The tool
output is fully validated before anything is written, so a failed or
malformed generation never leaves a partial roadmap; persistence is a single
transaction. Each task is scheduled onto a concrete weekday starting today.

Key resolution is platform-only Groq (see idea_interview.resolve_api_key) —
roadmap generation happens right after onboarding, before most orgs have
saved any BYOK key.

Regeneration comes in two grains: the whole roadmap (Project row kept, its
milestones/tasks replaced) and a single milestone (siblings untouched).
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import date

from openai import APIError, AsyncOpenAI, AuthenticationError, BadRequestError, RateLimitError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team
from src.services.cost_tracker import record_generation_cost
from src.services.idea_interview import _PURPOSE_GUIDANCE
from src.services.llm_errors import RATE_LIMIT_MESSAGE, LLMRateLimitError, is_rate_limit
from src.services.roadmap_shapes import (
    MAX_DAY_OFFSET as _MAX_DAY_OFFSET,
    MAX_MILESTONES as _MAX_MILESTONES,
    MAX_TASKS_PER_MILESTONE as _MAX_TASKS_PER_MILESTONE,
    MILESTONE_SCHEMA as _MILESTONE_SCHEMA,
    _add_tasks,
    _persist_milestones,
    _weekday_after,
    create_project_with_milestones,
    record_plan_quality,
    resolve_task_dependencies,
    validated_milestone as _validated_milestone,
    validated_milestones as _validated_milestones,
    validated_task as _validated_task,
)
from src.services.task_ids import allocate_short_ids
from src.worker import celery_app

logger = logging.getLogger(__name__)

_MODEL = settings.groq_model
# 8192, not 4096: a full plan is up to 8 milestones × 10 tasks, each carrying a
# 3-6 sentence technical description. At 4096 the tool call gets truncated and
# the roadmap comes back short.
_MAX_TOKENS = 8192
# Rough tokens→chars heuristic for the streamed draft's progress bar (English
# text averages ~4 chars/token). Capped below 100 in _call_planner_stream since
# validation/persistence still happen after the last byte arrives.
_PROGRESS_CHAR_ESTIMATE = _MAX_TOKENS * 4

_SYSTEM_PROMPT = f"""You are Omada's technical project planner. Given a founder's project brief, \
produce a day-by-day plan a developer can actually execute, sized to the project's ACTUAL \
complexity — not an exhaustive backlog, but not padded down to a token few phases either.

Make it genuinely DETAILED and TECHNICAL:
- Break the work into ordered milestones (phases), and size the plan to what the brief \
actually describes. A narrow, single-feature project might only need 2-4 milestones with a \
few tasks each. A genuinely complex project — multiple core features, integrations, or a \
broad scope/tech-constraints list — needs proportionally more: use as many milestones (up to \
{_MAX_MILESTONES}) and tasks per milestone (up to {_MAX_TASKS_PER_MILESTONE}) as the brief's \
`coreFeatures`, `scope`, and `techConstraints` justify. Don't compress real scope just to keep \
the plan short.
- Under each milestone, list concrete engineering tasks — each doable in part of a day.
- For EVERY task, write a detailed, technical `description` (3-6 sentences). Name the specific \
approach, technologies/libraries/frameworks, the files or modules to create, data models or \
schema, API endpoints, and key commands — and end with a crisp acceptance criterion for "done". \
Write for a technical reader; be concrete, never generic filler.
- Give every task a `dayOffset`: a 0-based index of WEEKDAYS from the start (0 = the first \
working day). Spread tasks so each day has only a few; let the plan run as long as the work \
genuinely requires, up to {_MAX_DAY_OFFSET} weekdays.
- Lay out each day as a realistic schedule: give every task a `startTime` (24h "HH:MM", \
between 09:00 and 18:00) and a `durationMinutes` (15–240). Order tasks within a day by time \
and don't overlap them — a developer should be able to follow the day top to bottom.
- Order milestones and tasks the way they should actually be tackled (dependencies first).
- Give every task a `key` (short, unique in this response, e.g. "setup-db"). When a task \
genuinely depends on other specific work finishing first, list those tasks' `key`s in \
`dependsOn` — reference the actual prerequisite tasks, not just "the one before it". \
Independent tasks (e.g. two unrelated setup steps that both feed into a later integration \
task) should have no `dependsOn` between them, so they can be worked in parallel; a task that \
only needs to happen after everything before it in its own track should list that specific \
task, not its whole history.
- Ground everything in THIS project and its stated stack/constraints. Never invent facts the \
brief doesn't support; where the brief is silent, make a sensible, clearly-reasonable technical \
choice and state it."""


_ENV_SETUP_GUIDANCE = (
    "The first milestone must include explicit tasks for setting up the local "
    "development environment this project needs: installing the language "
    "runtime/package manager, required CLI tools, framework or SDK installs, "
    "and creating accounts or API keys for any required third-party services "
    "— before any feature-building tasks. Base these on the project's actual "
    "stack; don't assume the developer's machine is already configured for "
    "this specific project."
)


def _system_prompt(purpose: str | None) -> str:
    guidance = _PURPOSE_GUIDANCE.get(purpose or "")
    if not guidance:
        return _SYSTEM_PROMPT
    return _SYSTEM_PROMPT + "\n" + guidance


_ROADMAP_TOOL = {
    "type": "function",
    "function": {
        "name": "build_roadmap",
        "description": "Produce a short-term, day-by-day roadmap for the project.",
        "parameters": {
            "type": "object",
            "properties": {
                "projectName": {"type": "string", "description": "Short name for the project"},
                "summary": {"type": "string", "description": "One or two sentence summary of the plan"},
                "milestones": {
                    "type": "array",
                    "description": "Ordered phases of work",
                    "items": _MILESTONE_SCHEMA,
                },
            },
            "required": ["milestones"],
        },
    },
}

_MILESTONE_TOOL = {
    "type": "function",
    "function": {
        "name": "rebuild_milestone",
        "description": "Re-plan a single milestone of the roadmap, leaving the others untouched.",
        "parameters": _MILESTONE_SCHEMA,
    },
}


def _tech_stack_prompt(session: OnboardingSession) -> str | None:
    """Renders the founder's explicit tech-stack answer (see PUT /tech-stack
    in onboarding_v2.py) as prompt guidance. Returns None when unset — either
    the tech_stack_step flag was off for this session, or it predates the
    feature — so older sessions keep generating exactly as before.

    Distinct from ProjectBrief.tech_constraints (chat-extracted, free text
    about hard requirements/integrations): this is about tool familiarity.
    """
    experience = session.tech_experience
    if experience == "experienced":
        stack = ", ".join(session.known_tech_stack or [])
        return (
            f"The founder already knows: {stack}. Prefer these tools; only introduce "
            "something new if there's a clear, well-justified gap in what they listed, "
            "and say why in the task description. Knowing a tool isn't the same as "
            "having it installed for this project — still give the first milestone "
            "explicit setup tasks for the chosen stack."
        )
    if experience == "new":
        return (
            "The founder is new to building software — this may be their first project. "
            "Recommend a simple, well-documented, beginner-friendly stack, and make the "
            "early setup/installation/account-creation steps explicit tasks in the first "
            "milestone, not assumed prior knowledge."
        )
    return None


def _brief_prompt(session: OnboardingSession) -> str:
    parts = [
        f"Project brief (JSON):\n{json.dumps(session.project_brief or {})}",
        _ENV_SETUP_GUIDANCE,
    ]
    tech_stack_guidance = _tech_stack_prompt(session)
    if tech_stack_guidance:
        parts.append(tech_stack_guidance)
    return "\n\n".join(parts)


def _milestone_prompt(
    milestone: Milestone, siblings: list[Milestone], session: OnboardingSession
) -> str:
    outline = [
        {"title": m.title, "description": m.description, "isTarget": m.id == milestone.id}
        for m in siblings
    ]
    return "\n\n".join(
        [
            _brief_prompt(session),
            f"Current roadmap outline (JSON):\n{json.dumps(outline)}",
            "Re-plan ONLY the milestone marked isTarget — its title, description, and "
            "tasks. The other milestones are fixed context; do not change or repeat "
            f'their work. Call rebuild_milestone with the new plan for "{milestone.title}".',
        ]
    )


# A full multi-milestone roadmap is a large, deeply-nested tool call, and Groq's
# tool-calling occasionally emits it in a form its own parser rejects
# (400 tool_use_failed) even though the underlying JSON was well-formed —
# Groq's own guidance is to retry. A single milestone rarely hits this.
_MAX_TOOL_RETRIES = 2


async def _call_planner(api_key: str, system: str, user_content: str, tool: dict):
    """One forced-tool Groq call, retried on tool_use_failed. Returns (tool_input dict, usage)."""
    tool_name = tool["function"]["name"]
    client = AsyncOpenAI(api_key=api_key, base_url=settings.groq_base_url)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    response = None
    for attempt in range(_MAX_TOOL_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
            break
        except AuthenticationError as exc:
            logger.error("Groq authentication failed — check GROQ_API_KEY", exc_info=True)
            raise ValueError("Invalid Groq API key.") from exc
        except RateLimitError as exc:
            logger.warning("Groq rate limit hit on %s (attempt %s)", tool_name, attempt + 1)
            raise LLMRateLimitError(RATE_LIMIT_MESSAGE) from exc
        except BadRequestError as exc:
            if getattr(exc, "code", None) == "tool_use_failed" and attempt < _MAX_TOOL_RETRIES:
                # The model returned a malformed tool call. Retrying usually
                # fixes it, but a rising rate here means the prompt or schema
                # has drifted — so don't retry silently.
                logger.warning(
                    "Groq tool_use_failed, retrying",
                    extra={"tool": tool_name, "attempt": attempt + 1, "max_retries": _MAX_TOOL_RETRIES},
                )
                continue
            logger.error("Groq bad request for %s: %s", tool_name, exc, exc_info=True)
            raise RuntimeError(f"Groq API error: {exc}") from exc
        except APIError as exc:
            logger.error("Groq API error for %s: %s", tool_name, exc, exc_info=True)
            raise RuntimeError(f"Groq API error: {exc}") from exc

    if response is None:
        # Unreachable today (the final attempt re-raises rather than continuing),
        # but an off-by-one in _MAX_TOOL_RETRIES would otherwise surface as an
        # opaque AttributeError on None instead of naming the real cause.
        logger.error("Groq returned no response for %s after all retries", tool_name)
        raise RuntimeError("The planner did not return a roadmap. Please try again.")

    tool_calls = response.choices[0].message.tool_calls or []
    call = next((t for t in tool_calls if t.function.name == tool_name), None)
    if call is None:
        raise RuntimeError("The planner did not return a roadmap. Please try again.")
    try:
        return json.loads(call.function.arguments), response.usage
    except json.JSONDecodeError as exc:
        raise RuntimeError("The planner returned malformed output. Please try again.") from exc


async def _call_planner_stream(
    api_key: str,
    system: str,
    user_content: str,
    tool: dict,
    on_progress: Callable[[int], Awaitable[None]] | None,
):
    """Streamed sibling of `_call_planner`, used only by `generate_roadmap` (the
    plan-review draft's critical path) so the UI can show real progress instead
    of a fake timer. Same forced-tool-call and retry semantics, but accumulated
    from `delta.tool_calls[].function.arguments` fragments.

    Mid-stream tool_use_failed surfaces as a bare APIError (not BadRequestError
    like the non-streamed path gets) since the SDK doesn't map SSE-delivered
    error events to status-code subclasses the way it does HTTP responses —
    confirmed against the real Groq endpoint, not just SDK docs.
    """
    tool_name = tool["function"]["name"]
    client = AsyncOpenAI(api_key=api_key, base_url=settings.groq_base_url)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    for attempt in range(_MAX_TOOL_RETRIES + 1):
        arguments = ""
        usage = None
        try:
            stream = await client.chat.completions.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": tool_name}},
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if chunk.usage is not None:
                    usage = chunk.usage
                if not chunk.choices:
                    continue
                for tc in chunk.choices[0].delta.tool_calls or []:
                    frag = tc.function.arguments if tc.function else None
                    if frag:
                        arguments += frag
                        if on_progress is not None:
                            pct = min(round(len(arguments) / _PROGRESS_CHAR_ESTIMATE * 100), 95)
                            await on_progress(pct)
        except AuthenticationError as exc:
            raise ValueError("Invalid Groq API key.") from exc
        except RateLimitError as exc:
            logger.warning("Groq rate limit hit streaming %s (attempt %s)", tool_name, attempt + 1)
            raise LLMRateLimitError(RATE_LIMIT_MESSAGE) from exc
        except APIError as exc:
            # Checked before the tool_use_failed retry: a rate limit that
            # arrives mid-stream isn't a RateLimitError (see llm_errors.
            # is_rate_limit), and it must stop the generation rather than
            # spend another attempt on the same exhausted quota.
            if is_rate_limit(exc):
                logger.warning("Groq rate limit mid-stream on %s: %s", tool_name, exc)
                raise LLMRateLimitError(RATE_LIMIT_MESSAGE) from exc
            if getattr(exc, "code", None) == "tool_use_failed" and attempt < _MAX_TOOL_RETRIES:
                continue
            raise RuntimeError(f"Groq API error: {exc}") from exc

        if not arguments:
            if attempt < _MAX_TOOL_RETRIES:
                continue
            raise RuntimeError("The planner did not return a roadmap. Please try again.")
        try:
            return json.loads(arguments), usage
        except json.JSONDecodeError:
            if attempt < _MAX_TOOL_RETRIES:
                continue
            raise RuntimeError("The planner returned malformed output. Please try again.")


# ─── public API ────────────────────────────────────────────────────────────────
async def generate_roadmap(
    session: OnboardingSession,
    team: Team,
    api_key: str,
    db: AsyncSession,
    on_progress: Callable[[int], Awaitable[None]] | None = None,
) -> Project:
    """Generate and persist a roadmap for `session` under `team`. Returns the
    new Project with milestones+tasks flushed. Assumes no project exists yet for
    the session (the router enforces that).

    `on_progress`, when given, is called with a 0-95 percent estimate as the
    forced tool call streams in — see _call_planner_stream."""
    data, usage = await _call_planner_stream(
        api_key,
        _system_prompt(session.project_purpose),
        _brief_prompt(session),
        _ROADMAP_TOOL,
        on_progress,
    )
    milestones = _validated_milestones(data)

    name = (
        data.get("projectName")
        or (session.project_brief or {}).get("projectName")
        or team.name
        or "My project"
    )
    project = await create_project_with_milestones(
        session, team, name, data.get("summary"), session.project_purpose, milestones, db,
    )
    # A repo may already have been picked during onboarding's repo-select step
    # before this project existed (PUT /repo just stashes it on the session in
    # that case) — copy it onto the freshly created Project now.
    if session.selected_github_repo_full_name:
        project.github_repo_full_name = session.selected_github_repo_full_name

    await record_generation_cost(
        "roadmap_generate",
        usage,
        provider="groq",
        org_id=team.organization_id,
        team_id=team.id,
        model=_MODEL,
        session_id=str(session.id),
    )
    await db.commit()
    await db.refresh(project)
    return project


async def generate_roadmap_once(
    session: OnboardingSession,
    team: Team,
    api_key: str,
    db: AsyncSession,
    on_progress: Callable[[int], Awaitable[None]] | None = None,
) -> Project:
    """`generate_roadmap`, safe against a concurrent writer for the same
    session — the prewarm Celery task below and `POST /plan/draft` can now
    legitimately race to generate for the same session. `Project.
    onboarding_session_id` is unique, so the loser's commit raises
    IntegrityError; roll back and return the winner's project instead of
    erroring out from underneath the loser."""
    # Captured before the possible rollback below: AsyncSession.rollback()
    # expires every object already loaded on `db` (including `session`
    # itself), so `session.id` after that point would trigger an implicit
    # lazy-load outside of an async context and raise MissingGreenlet.
    session_id = session.id
    try:
        return await generate_roadmap(session, team, api_key, db, on_progress)
    except IntegrityError:
        await db.rollback()
        project = await db.scalar(
            select(Project).where(Project.onboarding_session_id == session_id)
        )
        if project is None:
            raise
        return project


async def regenerate_roadmap(
    session: OnboardingSession, team: Team, api_key: str, db: AsyncSession
) -> Project:
    """Regenerate the whole roadmap. The Project row (and its id) is kept; its
    milestones and tasks are replaced wholesale, so task statuses reset.
    Generation and validation happen before anything is deleted — a failed call
    leaves the existing roadmap untouched. Falls back to `generate_roadmap`
    when no project exists yet."""
    project = await db.scalar(
        select(Project).where(Project.onboarding_session_id == session.id)
    )
    if project is None:
        return await generate_roadmap(session, team, api_key, db)

    data, usage = await _call_planner(
        api_key,
        _system_prompt(session.project_purpose),
        _brief_prompt(session),
        _ROADMAP_TOOL,
    )
    milestones = _validated_milestones(data)

    milestone_ids = select(Milestone.id).where(Milestone.project_id == project.id)
    await db.execute(delete(Task).where(Task.milestone_id.in_(milestone_ids)))
    await db.execute(delete(Milestone).where(Milestone.project_id == project.id))

    if data.get("projectName"):
        project.name = str(data["projectName"])[:255]
    if data.get("summary"):
        project.summary = data["summary"]
    org = await db.get(Organization, team.organization_id)
    await _persist_milestones(project, milestones, org, db, source="regenerate")

    await record_generation_cost(
        "roadmap_regenerate",
        usage,
        provider="groq",
        org_id=team.organization_id,
        team_id=team.id,
        model=_MODEL,
        session_id=str(session.id),
    )
    await db.commit()
    await db.refresh(project)
    return project


async def regenerate_milestone(
    milestone: Milestone, session: OnboardingSession, api_key: str, db: AsyncSession
) -> Milestone:
    """Re-plan a single milestone; every other milestone is untouched. The
    target's tasks are replaced wholesale (statuses reset) and its title/
    description updated; its position (`sort_order`) is kept. Validation
    happens before any delete, so a failed call changes nothing.

    Known limitation: because `_MILESTONE_TOOL`'s schema only returns this
    one milestone's tasks, a single-milestone regenerate can only express
    dependencies *within* it — there's no way for the model to reference a
    sibling milestone's task keys. And because this wholesale-deletes the
    milestone's old tasks, any pre-existing edges from other milestones'
    tasks into this milestone's old tasks are cascade-deleted along with
    them. This mirrors how the old `parallel` flag was reset the same way on
    regenerate — not a new regression, just worth calling out.
    """
    siblings = (
        (
            await db.execute(
                select(Milestone)
                .where(Milestone.project_id == milestone.project_id)
                .order_by(Milestone.sort_order)
            )
        )
        .scalars()
        .all()
    )

    data, usage = await _call_planner(
        api_key,
        _system_prompt(session.project_purpose),
        _milestone_prompt(milestone, siblings, session),
        _MILESTONE_TOOL,
    )
    new = _validated_milestone(data, milestone.sort_order)
    if not new["tasks"]:
        raise RuntimeError("The planner returned an empty milestone. Please try again.")

    await db.execute(delete(Task).where(Task.milestone_id == milestone.id))
    milestone.title = new["title"]
    milestone.description = new["description"]
    org_row = (
        await db.execute(
            select(Organization, Team.id)
            .join(Team, Team.organization_id == Organization.id)
            .join(Project, Project.team_id == Team.id)
            .where(Project.id == milestone.project_id)
        )
    ).first()
    org, milestone_team_id = org_row
    short_ids = await allocate_short_ids(org, len(new["tasks"]), db)
    tasks_by_key = _add_tasks(milestone.id, new["tasks"], date.today(), short_ids, db)
    edges_by_key = {t.get("key"): t.get("depends_on") or [] for t in new["tasks"]}
    resolution = resolve_task_dependencies(tasks_by_key, edges_by_key, strict=True)
    # Scoped to this milestone's edges only — _MILESTONE_TOOL can't express a
    # cross-milestone dependency (see this function's docstring), so the counts
    # describe the re-planned milestone, not the whole project.
    project = await db.scalar(select(Project).where(Project.id == milestone.project_id))
    if project is not None:
        record_plan_quality(project, resolution, "regenerate_milestone")

    await record_generation_cost(
        "roadmap_regenerate_milestone",
        usage,
        provider="groq",
        org_id=org.id,
        team_id=milestone_team_id,
        model=_MODEL,
        session_id=str(session.id),
        milestone_id=str(milestone.id),
    )
    await db.commit()
    await db.refresh(milestone)
    return milestone


# ─── background pre-generation ─────────────────────────────────────────────────
# `purpose`/`tech_stack` are known and `project_brief` is updated after every
# chat turn, well before the founder ever reaches the plan-review step — so as
# soon as the interview completes (`session.status == "completed"`), we can
# generate the roadmap in the background instead of on the review step's
# critical path. See onboarding_v2._maybe_prewarm_roadmap for the trigger.
async def _prewarm_roadmap_async(session_id: str, db: AsyncSession) -> None:
    # `session_id` arrives as a plain string (Celery JSON-serializes task
    # args) — `db.get`'s identity lookup needs an actual UUID for its bind
    # processor, unlike filter comparisons elsewhere which coerce it fine.
    session = await db.get(OnboardingSession, uuid.UUID(session_id))
    if session is None or session.status != "completed" or not session.project_brief:
        return
    existing = await db.scalar(
        select(Project).where(Project.onboarding_session_id == session.id)
    )
    if existing is not None:
        return
    if not settings.groq_api_key:
        logger.warning(
            "prewarm_roadmap: no Groq API key configured, skipping session %s", session_id
        )
        return
    team = await db.scalar(
        select(Team).where(Team.organization_id == session.organization_id).order_by(Team.created_at)
    )
    if team is None:
        logger.warning("prewarm_roadmap: no team for session %s, skipping", session_id)
        return
    await generate_roadmap_once(session, team, settings.groq_api_key, db)


@celery_app.task(bind=True, max_retries=1)
def prewarm_roadmap(self, session_id: str):
    """Best-effort background pre-generation. This is purely a perf
    optimization — `POST /plan/draft` still generates synchronously if this
    hasn't finished (or failed) by the time the founder reaches plan-review —
    so retries are kept minimal rather than chasing this indefinitely."""
    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            try:
                await _prewarm_roadmap_async(session_id, db)
            except Exception:
                await db.rollback()
                raise

    try:
        asyncio.run(_run())
    except LLMRateLimitError:
        # Give up instead of retrying: 15 seconds later we'd hit the same
        # quota window, and this task is only a prefetch — POST /plan/draft
        # generates on demand when the founder actually reaches plan-review.
        logger.warning(
            "prewarm_roadmap: Groq rate limit for session %s, skipping prewarm", session_id
        )
    except Exception as exc:  # pragma: no cover — exercised via retry semantics, not unit tests
        logger.exception("prewarm_roadmap failed for session %s", session_id)
        raise self.retry(exc=exc, countdown=15)
