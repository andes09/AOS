# Initiative B — Execution Plan

**Date**: 2026-05-27
**Source spec**: `tasks/todo.md` → "Initiative B — Inline Ticket Refinement" (lines 389–553)
**Status**: planning approved (pending kickoff)
**Sibling**: Initiative A is merged (`ba871df`); B is independent and can start immediately.

## Decisions locked in (defaults from spec's "Open questions")

- **Editor reachable on `ready` tickets**: yes, soft-styled hint, no hard gate. (Open Q1)
- **ADF vs plain text**: v1 plain text in/out. ADF round-tripping deferred to v2. (Open Q2)
- **Bulk-approve threshold**: hardcoded `5`. Revisit after a quarter of usage. (Open Q3)
- **Story-point side-effects**: persist quietly; surface "ticket points changed — re-plan capacity?" banner inside B8 before [Review and Commit]. No auto-replan. (Open Q4)
- **Assignee / mentions**: description-only; no Jira mention round-tripping. (Open Q5)
- **30-ticket sprints**: ship as-is; monitor B7 telemetry on session-completion time; revisit only if median > 3min. (Open Q6)
- **Save Draft**: drafts tied to `plan_id` UUID; new plan generation = new id, old draft orphaned but retained 30 days. (Open Q7)

Migration numbering already verified: highest existing = `0019_recalibration_proposals.py`. **0020** and **0021** are free (spec's bumped numbers stand).

## Codebase reference (verified 2026-05-27)

| Concern | Path | Notes |
|---|---|---|
| Sprint Brain plan endpoint | `apps/api/src/routers/sprint_brain.py:525-586` | `create_sprint_plan` calls `_extract_plan` then `_build_enrichment` at L576 — Scope Cop hook goes between |
| Sprint Brain enrichment | `apps/api/src/routers/sprint_brain.py:256-415` | `_build_enrichment` already pulls Scope Cop analyses; B0 ensures the analyses exist before this runs |
| Existing push-to-Jira (to deprecate from planner) | `apps/api/src/routers/sprint_brain.py:635` | `push_to_jira` — gated by `push_to_jira` feature flag; B10's `/commit` supersedes this for the new flow |
| Scope Cop tool schema | `apps/api/src/services/scope_cop.py:106` | `_SCOPE_COP_TOOL` — extend with `suggested_revision` object |
| Scope Cop `analyze_tickets` | `apps/api/src/services/scope_cop.py:389-540` | Upserts into `ticket_analyses` ON CONFLICT (L462+) — new column auto-flows |
| Scope Cop prompt builder | `apps/api/src/services/scope_cop.py:286` | `_build_prompt` — update to instruct Claude to produce fix *content*, not descriptions |
| TicketAnalysis ORM | `apps/api/src/models/scope_cop.py:19` | Add `suggested_revision: Mapped[dict]` JSON column |
| Jira client | `apps/api/src/integrations/jira/client.py` | `assign_issue` exists at L166; need new `update_issue(key, fields)` PUT `/rest/api/3/issue/{key}` |
| Jira OAuth scopes | `apps/api/src/integrations/jira/oauth.py:7-69` | `write:issue:jira` (L28) + `write:issue:jira-software` (L69) **already requested** — no scope upgrade needed for existing connections (verify in SB-3) |
| Highest migration | `apps/api/alembic/versions/0019_recalibration_proposals.py` | Next free: 0020, 0021 |
| Sprint Planner page | `apps/web/src/pages/SprintPlannerPage.tsx` | `generatePlan` mutation L119–127 (`setPlan` on success) — hook PlanReviewModal here; ScopeCopPanel at L359 |
| Sprint components dir | `apps/web/src/components/sprint/` | Add `TicketEditorPane.tsx`, `PlanReviewModal.tsx`, `SignOffCarousel.tsx` |
| Existing Scope Cop UI | `apps/web/src/components/sprint/ScopeCopPanel.tsx` | B6 "Refine" buttons graft here |

## Subagent waves (moderate parallelism — ~3 parallel per wave)

### Wave 0 — Foundations (3 parallel, no dependencies)

| ID | Task | Files | Maps to |
|---|---|---|---|
| SB-1 | Alembic 0020 + ORM + Pydantic for `suggested_revision` | `apps/api/alembic/versions/0020_ticket_analyses_suggested_revision.py` (add JSON column); `apps/api/src/models/scope_cop.py` (new field); `TicketAnalysisResult` + `AnalyzeResponse` Pydantic models | B1 (schema slice) |
| SB-2 | Alembic 0021 + `TicketRevision` ORM | `apps/api/alembic/versions/0021_ticket_revisions.py` (id, ticket_id FK, suggested_revision JSON, applied_revision JSON, original_jira_state JSON, applied_at, applied_by); `apps/api/src/models/ticket_revision.py` ORM | B3 (table slice) |
| SB-3 | Jira write capability + scope audit | Verify `JiraConnection` rows already hold a token with `write:issue:jira` (oauth.py:28) — write a startup check / one-off script; add `JiraClient.update_issue(key, fields)` (PUT `/rest/api/3/issue/{key}`) + `apps/api/tests/integrations/test_jira_update_issue.py` against the existing sandbox fixtures | B2 |

**Wave 0 exit gate**: migrations apply cleanly on a fresh DB; `JiraClient.update_issue` round-trips title + description + story-points against the sandbox.

### Wave 1 — Scope Cop content generation + pipeline wiring (3 parallel, depends on Wave 0)

| ID | Task | Files | Maps to |
|---|---|---|---|
| SB-4 | Extend Scope Cop to emit `suggested_revision` | `apps/api/src/services/scope_cop.py:106` — add `suggested_revision: {title, description, acceptance_criteria[], story_points}` to `_SCOPE_COP_TOOL`; rewrite `_build_prompt` (L286) and system instructions to make Claude produce the fix *content* per criterion; update upsert at L462+ to persist the new column; `apps/api/tests/test_scope_cop_suggestions.py` — fixture ticket with missing AC produces plausible AC strings | B1 (service + prompt) |
| SB-5 | Wire Sprint Brain → Scope Cop auto-run | `apps/api/src/routers/sprint_brain.py:576` — after `_extract_plan` returns assignments, call `scope_cop.analyze_tickets(team_id, assigned_keys, jira_client, db)` *before* `_build_enrichment`; wrap in try/except (must not block plan); add `scope_cop_ran_at: datetime \| None` to `SprintPlanResponse`; tests: planning generates analyses for all assigned tickets; Scope Cop failure → plan still returns | B0 |
| SB-6 | Conflict detection plumbing | Expose `fields.updated` from `JiraClient.get_issue` in the API responses Scope Cop and the plan endpoint return (so the modal has `fetched_updated_at` to send back); helper `JiraClient.check_stale(key, fetched_updated_at) -> bool`; tests: stale issue returns True | B3 (detection slice — audit-row writes land in SB-8) |

**Wave 1 exit gate**: generating a plan against the sandbox populates `ticket_analyses.suggested_revision` for every assigned key; `scope_cop_ran_at` returned to client; a manual stale-check confirms the dirty-detection helper.

### Wave 2 — Backend endpoints (2 parallel, depends on Wave 1)

| ID | Task | Files | Maps to |
|---|---|---|---|
| SB-7 | Single-ticket revision endpoints | New router `apps/api/src/routers/scope_cop_revisions.py` (mounted in `apps/api/src/main.py`): GET `/api/scope-cop/tickets/{key}/revision-preview` → returns `{original, suggested_revision, fetched_updated_at}` (reads cached `ticket_analyses.suggested_revision`, runs fresh Scope Cop if absent); PATCH `/api/scope-cop/tickets/{key}` → body `{revision, fetched_updated_at}`; performs stale check (409 on mismatch), calls `JiraClient.update_issue`, writes `ticket_revisions` row, re-runs Scope Cop scoring on the updated content; lead role required; tests cover dirty-check, 409 path, audit-row written, scoring re-run | B4 |
| SB-8 | Batched commit endpoint | Add `POST /api/sprint-brain/plans/{plan_id}/commit` to `apps/api/src/routers/sprint_brain.py` — body `{ approvals: [{ticket_key, revision?, approved_at, fetched_updated_at}] }`; per ticket: if `revision` present, `JiraClient.update_issue`; for *all* tickets, set Jira sprint custom field + assignee (reuse logic from existing `push_to_jira` at L636); write `ticket_revisions` row per ticket (revision nullable); atomic-ish: collect per-ticket results → return `{committed: [...], conflicts: [...]}`; lead role; tests: happy path, partial 409, audit rows | B10 |

**Wave 2 exit gate**: postman / curl smoke against sandbox — single PATCH lands an edit; batched commit pushes a mixed (some edited, some unedited) approval set; 409 surfaces correctly.

### Wave 3 — UI components (3 parallel, depends on Wave 2 for API contracts)

| ID | Task | Files | Maps to |
|---|---|---|---|
| SB-9 | `TicketEditorPane` component | `apps/web/src/components/sprint/TicketEditorPane.tsx` — side-by-side layout (original left read-only, suggested editable right); diff-highlight on changed fields using `diff` npm package (add to `apps/web/package.json`); per-field "Reset to suggestion" button; `currentState` vs `originalState` per ticket exposed via props so parent modal can compute global dirty; `apps/web/src/components/sprint/__tests__/TicketEditorPane.test.tsx` (vitest) — dirty logic, reset button, diff render | B5 |
| SB-10 | `PlanReviewModal` shell | `apps/web/src/components/sprint/PlanReviewModal.tsx` — full-screen takeover; three-pane: left rail (scrollable, status pill + assignee avatar + title + points, click to select); center renders `<TicketEditorPane />`; right rail (assignee name, current sprint load `assigned/safe_capacity`, velocity citation from plan's `reasoning`, "reassign" link); top-right [Save Draft] (persists edits keyed by `plan_id` to localStorage with 30-day TTL — backend persistence is v2); bottom-right [Review and Commit] (always enabled); story-point-change banner shown when any ticket's `story_points` diff != 0; keyboard: `j`/`k` and `↑`/`↓` rail nav, `Cmd+Enter` opens carousel; tests: rail render, selection routing, keyboard nav, sp-change banner | B8 |
| SB-11 | `SignOffCarousel` component | `apps/web/src/components/sprint/SignOffCarousel.tsx` — full-screen, one ticket per screen; header `Ticket N of M` + ticket key + assignee chip; body shows original + revised + Sprint Brain reasoning; footer: [Approve], [Go back to edit] (returns to B8 with this ticket selected), [Approve next 5] (only when ≥5 unapproved remain — hardcoded threshold per locked decision); session-scoped approval memory in React state `{ticket_id: approved_at}`; **editing a ticket in B8 clears its prior approval** (parent passes `lastEditedAt` per ticket; carousel compares against `approvedAt`); final screen: commit summary card + [Push to Jira] → calls SB-8's `/commit`; Esc / Back to Triage preserves approvals; tests: memory across nav, edit-invalidates-own-approval, bulk-approve records 5 distinct timestamps, final-screen gating | B9 |

**Wave 3 exit gate**: Storybook / dev-server walkthrough — open the modal on a mock plan with fixture data, navigate the rail, edit a ticket, enter carousel, approve 3, go back, re-approve confirmed. All three components in isolation, no backend yet.

### Wave 4 — Wiring + ancillary surfaces (3 parallel, distinct files)

| ID | Task | Files | Maps to |
|---|---|---|---|
| SB-12 | Sprint Planner integration + auto-open | `apps/web/src/pages/SprintPlannerPage.tsx` — after `generatePlan` onSuccess (L127), set state to open `<PlanReviewModal />` automatically (gated behind feature flag for safe rollout); remove or hide the legacy ad-hoc "Push to Jira" CTA in favor of the modal's [Review and Commit] flow; wire commit → SB-8's `/commit` → re-fetch plan / scope cop cache on success; surface partial-conflict response with per-ticket retry affordance | B8 wiring |
| SB-13 | One-off "Refine" entry points | `apps/web/src/components/sprint/ScopeCopPanel.tsx` — non-ready rows get a "Refine" button → opens a lightweight single-ticket variant of `TicketEditorPane` (modal or drawer wrapping just that pane), hitting SB-7's GET preview + PATCH endpoints (NOT the batched flow); also surface inline in Sprint Planner warnings; after successful push, invalidate the scope-cop analysis query so the row's score updates | B6 |
| SB-14 | Telemetry + Exec Dashboard chart | New events in `apps/api/src/services/telemetry.py` (or wherever PostHog/analytics calls live — discover at task start): `revisions_proposed`, `revisions_accepted_verbatim`, `revisions_edited_before_push`, `revisions_dismissed`, plus per-field edit-rate flags; SB-8's commit endpoint emits these; Exec Dashboard component: "Scope Cop revision acceptance rate, trailing 8 sprints"; threshold alert at `<0.3` acceptance rate surfaces banner "Scope Cop suggestions aren't landing — review the prompt" | B7 |

**Wave 4 exit gate**: full vertical slice works end-to-end against the sandbox — generate plan → modal opens → edit one ticket → carousel → push → Jira reflects edits + sprint assignment, `ticket_revisions` rows written, telemetry events fired, Exec Dashboard renders the chart.

### Wave 5 — Verification + simulator pass (single coordinated pass — no parallelism)

- **Manual e2e**: planning → Scope Cop auto-run populates `suggested_revision` → modal opens → edit a ticket in B8 → carousel approvals (including a bulk-approve-next-5) → batched push → Jira sandbox reflects edits + sprint + assignee → audit rows verified.
- **Conflict path**: edit a ticket in Jira UI mid-flow, attempt push, confirm per-ticket 409 surfaces in the carousel's "conflicts" partial response with a retry affordance.
- **Story-point side-effect banner**: bump points from 3→5 in B8, confirm the "re-plan capacity?" banner appears before [Review and Commit].
- **Approval memory**: approve 3 in carousel → back to B8 → edit ticket #4 → return; #1–#3 still approved, #4 requires re-approval if you also edited it again.
- **omada-simulator**: run on `balanced` archetype with B-pipeline enabled (Scope Cop auto-run on every assigned ticket + revisions accepted at the simulator's default rate). Confirm `plan_ok_pct` ≥ baseline post-Initiative-A — i.e. Initiative B is at least neutral on plan quality. Investigate any regression before merge.
- **Audit-trail spot-check**: 5 random `ticket_revisions` rows — `original_jira_state` snapshot is complete enough to support a future rollback feature (title, description, AC custom field, story points, assignee, sprint id all captured).
- **Acceptance-rate sanity**: telemetry rows for SB-14's events present; Exec Dashboard chart renders with at least one sprint's worth of data.

## Risk register

| Risk | Mitigation |
|---|---|
| Scope Cop auto-run on every plan inflates Claude bill | Reuse existing per-team token budget guard from Initiative A; B0's try/except already prevents plan-blocking on rate-limit |
| Plain-text description push loses Jira formatting (checklists, mentions) | v2 ADF item is explicit in spec; surface a one-time tooltip on first edit warning users that complex formatting may be flattened |
| Batched commit partial failure leaves a confusing state | SB-8 returns `{committed, conflicts}`; carousel's final screen renders "N pushed, M conflicts" and lets user fix + retry conflicts in isolation |
| `JiraConnection` rows from before scope grant lack `write:issue:jira` | SB-3 verifies the scope set is already requested in oauth.py:7-69 — confirm against existing tokens; if any pre-date the scope additions, add a one-time re-auth prompt (cost: tiny banner in settings) |
| User churns away from modal mid-edit, loses work | [Save Draft] writes to localStorage keyed by `plan_id`; on next modal open we restore. Backend draft persistence is v2 — accepted scope cut |

## Out of scope (deferred to v2)

- ADF round-tripping (Open Q2)
- Backend Save Draft persistence (Open Q7 — v1 is localStorage only)
- Auto-replan on story-point change (Open Q4 — banner only, no auto-action)
- Jira mention round-tripping (Open Q5)
- Configurable bulk-approve threshold (Open Q3)
- Rollback feature on `ticket_revisions` (audit row captures the snapshot; no UI yet)

## Suggested commit boundaries (one PR per wave)

1. `feat(inline-refinement): wave 0 — migrations 0020/0021 + Jira update_issue`
2. `feat(inline-refinement): wave 1 — Scope Cop suggested_revision + plan pipeline hook`
3. `feat(inline-refinement): wave 2 — revision-preview + batched commit endpoints`
4. `feat(inline-refinement): wave 3 — editor pane, plan review modal, sign-off carousel`
5. `feat(inline-refinement): wave 4 — planner integration + refine surfaces + telemetry`
6. `feat(inline-refinement): wave 5 — verification + simulator pass`

Six PRs, ~3 parallel subagents per wave, distinct files per subagent within a wave to keep merge conflicts at zero.
