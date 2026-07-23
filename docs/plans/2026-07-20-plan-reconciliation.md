# Plan Reconciliation — build order and cross-references for the 2026-07-20 plan set

## Context

Five plan docs landed on the same day (`docs/plans/2026-07-20-*.md`:
github-task-autocomplete, import-artifacts, master-dashboard, omada-mcp-server,
project-hub), each well-scoped and individually grounded in the codebase. Reviewed
together against the actual code (`apps/api/src/routers/roadmap.py`, model files,
`apps/api/alembic/versions/`, `apps/web/src/App.tsx`), several seams don't fully belong
to any one doc:

1. **Critical**: Project Hub moves roadmap data from one-project-per-org — DB-enforced
   today via two `unique=True` FKs (`OnboardingSession.organization_id`,
   `Project.onboarding_session_id`) — to multi-project-per-org, with every roadmap route
   becoming `project_id`-scoped. Omada MCP Server independently extracts *today's*
   single-project `roadmap.py` into a service layer and ships 8 tools with no
   `project_id` param anywhere. Neither doc references the other. If Project Hub lands
   first (or at all), the MCP tool surface becomes ambiguous the moment an org has more
   than one project.
2. Four of the five plans claim Alembic migration `0032` (several also `0033`), each
   with only a one-line "whichever lands first, others rebase" note — no doc states an
   actual order.
3. `Task.completed_at` is added independently by GitHub Task Auto-Complete and Omada MCP
   Server, both flagging the collision, neither committing to own it.
4. GitHub Task Auto-Complete's doc states, as a decided fact, that it supersedes Master
   Dashboard's §6 (the `github_commit_daily` table + its sync job) — but
   `master-dashboard.md` itself is unedited and still fully specs building that
   now-superseded pipeline as if the decision hadn't happened.
5. Minor: no plan covers how a human notices an auto-completed task (both auto-complete
   paths are framed as "closing the loop" but neither adds a notification). Multi-project
   also blurs Master Dashboard's per-org commit/cost rollup once Project Hub ships
   (mixes sibling projects' activity under one row).

This doc is the single place these decisions live, so each of the 5 plans can be read
(or edited) against one source of truth instead of five pairwise hedges.

## Decided build order

1. **Project Hub** — most foundational; everything else's "one roadmap per org" framing
   depends on whether this has landed.
2. **Import Artifacts** — already designed as a fast-follow off Project Hub's
   `/api/projects/sessions/{id}/...` prefix; no design change needed, just its migration
   number.
3. **GitHub Task Auto-Complete** — adds `Task.short_id` / `Task.completed_at`,
   supersedes Master Dashboard §6.
4. **Master Dashboard** — consumes `github_activity_events` from step 3 instead of
   building its own commit-sync pipeline.
5. **Omada MCP Server** — needs Project Hub's `project_id`-scoped model to design its
   tools correctly, and skips adding `Task.completed_at` since step 3 already adds it.

Migration chain: `0032` Project Hub → `0033` Import Artifacts → `0034` GitHub Task
Auto-Complete → `0035` Master Dashboard → `0036` Omada MCP Server task fields → `0037`
Omada MCP Server OAuth tables.

## Resolutions, per plan

### Project Hub
Recommended first in build order. Omada MCP Server's tool surface depends on its
`project_id` model (see below) — that plan should be read as depending on this one.
Migration stays `0032`, `down_revision = '0031'` (current head, confirmed).

### Import Artifacts
Migration `0033`, `down_revision` = Project Hub's `0032`. Its "one-project-per-org"
Context framing describes the founding-project case correctly — Project Hub's own
fast-follow note already covers extending import to additional projects later, no
design change needed here.

### GitHub Task Auto-Complete
Migration `0034`, `down_revision` = Import Artifacts' `0033`. Owns `Task.completed_at`
first — Omada MCP Server's migration must not re-add it (only adds `completion_note`).
`Task.short_id` uniqueness (per-org via `Organization.next_task_seq`) needs no change
post-Project-Hub: a `Task` always belongs to exactly one `Project` via `Milestone`
regardless of how many projects the org has. Complementary to Omada MCP Server as the
agent-driven completion path (commits/PRs vs. direct agent tool calls). Notifying the
project owner when auto-complete fires is explicitly out of scope for v1 (see Finding 5
above) — call this out rather than leave it silent.

### Master Dashboard
Migration `0035`, `down_revision` = GitHub Task Auto-Complete's `0034`. **§6 ("GitHub
commit sync (Celery)") is superseded**: drop the `github_commit_daily` table and
`commit_sync.py` build spec; the dashboard's commit endpoints
(`GET /api/platform-admin/commits`) read from `github_activity_events` instead, per the
decision already made in the GitHub Task Auto-Complete doc. Only `ai_usage_events`
remains in this plan's migration. The per-org commit/cost rollup (`GET /orgs`) becomes
approximate once Project Hub ships multi-project orgs — accepted as a v1 limitation,
not silently wrong.

### Omada MCP Server
Hard dependency on Project Hub landing first. Tool surface changes:
- Add a **9th tool, `list_projects`**, so an agent can discover which `project_id` to
  use before calling project-scoped tools — without this, a `project_id` param is
  correct but undiscoverable.
- `get_roadmap`, `get_task`, `list_tasks`, `get_next_task`, `complete_task`,
  `regenerate_milestone` all gain a `project_id` param. Resolution rule: if omitted and
  the org has exactly one active project, default to it; otherwise require it and error
  with the available project list (from `list_projects`).
- `roadmap_service.py` is written against the *post-Project-Hub* `roadmap.py` /
  `project_common.py` (project-scoped helpers), not today's org-only version — it
  becomes the MCP-specific layer on top of `project_common`'s ownership checks, adding
  the MCP-only functions (`claim_next_task`, `complete_task`, `list_projects`).
- Migrations: task-fields migration → `0036`, `down_revision` = Master Dashboard's
  `0035`, adds only `completion_note` (`completed_at` already exists from `0034`). OAuth
  tables migration → `0037`, `down_revision` = `0036`.
- Previously-open risk #6 (the `completed_at` collision) is resolved by the ownership
  decision above, not left open.

## Status

This doc records the decisions; the 5 source plans have not yet been edited to match.
Next step, if wanted: apply the migration-number, `down_revision`, and cross-reference
edits above directly to each of the 5 files, and rewrite Master Dashboard §6 and Omada
MCP Server's tool table/service-layer section as described.
