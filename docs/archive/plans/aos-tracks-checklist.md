# AOS Full Rebuild — Track Checklist

See full spec: `/Users/anshdesai/.claude/plans/federated-imagining-dream.md`

---

## Execution Model

### Why Waves
24 tracks cannot be fired simultaneously. Agents writing to the same router or model file will produce merge conflicts. DB migrations must be verified before any service code runs against them — a missing column causes a runtime error that silently passes if the service falls back to defaults. Wave structure enforces the dependency graph and keeps each agent's blast radius small.

### Hard Rules
- **Track 1 is Wave 0. Nothing else starts until it passes.** Every contract — paths, field names, types, status codes, nullable vs non-nullable — must be agreed and locked before any implementation track runs. A field name disagreement caught in Wave 0 costs minutes. Caught in Wave 4, it costs a full rewrite of the API layer and the TypeScript types simultaneously.
- **Never start a wave until all tracks in the previous wave are verified.** "Verified" means the verify step passed, not just that the code was written.
- **One agent per track.** Do not combine tracks into one agent to save time — they will collide on shared files (`main.py`, `models/__init__.py`, `App.tsx`, `DashboardLayout.tsx`).
- **Migrations are the riskiest step.** Run `python migrate.py` on a fresh DB after every wave that includes a migration track. If it fails, stop and fix before continuing.
- **Tracks 22–23 are integration tracks, not feature tracks.** They touch Sprint Brain, which is already live. Read `sprint_brain.py` in full before editing it. Verify the existing generate endpoint still works after each change.

### Shared Files — High Collision Risk
These files are touched by multiple tracks. Coordinate explicitly or assign one agent per file:

| File | Touched By |
|---|---|
| `apps/api/src/main.py` | Tracks 3, 5, 9, 11, 14, 17, 20 (every new router) |
| `apps/api/src/models/__init__.py` | Tracks 2, 13, 16, 19 (every new model) |
| `apps/api/src/routers/sprint_brain.py` | Tracks 5, 22, 23 |
| `apps/web/src/App.tsx` | Tracks 10, 21, 18, 24 |
| `apps/web/src/components/DashboardLayout.tsx` | Tracks 10, 18, 21, 24 |
| `apps/web/src/pages/SprintPlannerPage.tsx` | Tracks 6, 15, 22 |
| `apps/web/src/pages/VelocityMirrorPage.tsx` | Tracks 8, 18, 21 |

---

## Wave Structure

### Wave 0 — API Contracts ⛔ Hard Gate: nothing else starts until this passes
Track 1 only. No code is written. The output is a locked set of contracts that every subsequent agent is handed as ground truth. If contracts are ambiguous or incomplete, resolve them here — not mid-implementation.

| Track | What |
|---|---|
| Track 1 | Lock all API contracts (A–J) covering every new endpoint, request/response shape, field names, status codes, and the `enrichmentStatus` extension to `SprintPlanResponse` |

**Wave 0 gate:** Every contract in Track 1 is marked complete. All paths are `kebab-case`. All response fields are `camelCase`. All nullable fields are explicitly annotated. `enrichmentStatus` states and their exact string values are agreed. No implementation track may begin until this checklist item is checked.

---

### Wave 1 — DB Foundations (run together, verify all migrations before Wave 2)
All migration tracks. No service code, no endpoints, no frontend. Goal: every table and constraint exists before any code queries it.

| Track | What |
|---|---|
| Track 0 | DB Foundations — SAEnum fixes + team_members unique constraint |
| Track 2 | RBAC — `app_role` column on `developers` |
| Track 13 | Scope Cop — `ticket_analyses` table |
| Track 16 | Dependency Radar — `dependencies` table |
| Track 19 | Retro AI — `retrospectives` + `retro_patterns` tables |

**Wave 1 gate:** `python migrate.py` applies all migrations (0005–0009) cleanly on a fresh DB — note 0005 and 0006 do not yet exist and must be written as part of this wave. `SELECT table_name FROM information_schema.tables` shows all new tables. Zero runtime errors before proceeding.

---

### Wave 2 — Internal Logic (run together, no router registration yet)
Service files and Jira client extensions. No endpoints exposed. Each track is fully self-contained — no shared files except `models/__init__.py` (already finalized in Wave 1).

**Claude client note (Tracks 14, 20-A):** Service functions that call Claude accept `anthropic_api_key: str` as a parameter and create `anthropic.AsyncAnthropic(api_key=anthropic_api_key)` internally — same pattern as `generate_sprint_plan()` in `sprint_brain.py`. Routers call `await get_anthropic_key(clerk_org_id, db)` from `src/services/ai_client.py` (created in Track 0) and pass the result to the service. Do not fetch the key inside the service function.

| Track | What |
|---|---|
| Track 3 | RBAC auth dependency (`auth_roles.py` — no router yet, just the dependency factory) |
| Track 4 | Jira Push client methods (`JiraClient` extensions + `push.py` resolver) |
| Track 14 | Scope Cop service (`src/services/scope_cop.py`) |
| Track 17-A | Dependency Radar — `get_issue_links()` on `JiraClient` + `src/services/dependency_radar.py` only |
| Track 20-A | Retro AI service (`src/services/retro_ai.py`) only |

**Wave 2 gate:** Unit test each service function in isolation (mock DB, mock Jira client). `auth_roles.py` dependency resolves correct role for seeded developers. No `main.py` changes yet.

---

### Wave 3 — API Endpoints (run together after Wave 2)
All router files and `main.py` registrations. Each track adds one router. `main.py` is the only shared file — assign it to a single cleanup pass at the end of this wave rather than having each agent append to it.

| Track | What |
|---|---|
| Track 3 (finish) | Register `users_router` in `main.py`; wire role endpoints |
| Track 5 | Jira Push endpoint in `sprint_brain.py` |
| Track 7 | Velocity Stats `from_date` filter in `routers/velocity.py` (adds param + filter to existing endpoint) |
| Track 9 | Exec Dashboard router (`exec.py`) |
| Track 11 | Developer Profile router (`developers.py`) |
| Track 14 (finish) | Scope Cop router (`scope_cop.py`) + register in `main.py` |
| Track 17 (finish) | Dependency Radar router (`dependency_radar.py`) + register in `main.py` |
| Track 20 (finish) | Retro AI router (`retro.py`) + register in `main.py` |

**Wave 3 gate:** `GET /docs` loads without import errors. All new endpoints appear in the OpenAPI spec. Role guards return 403 for insufficient role on every gated route. Run the positive-path verify for Tracks 14 and 17 (analyze 3 tickets, scan Jira deps) before moving to frontend.

---

### Wave 4 — Frontend (run together after Wave 3)
All React pages and component files. `App.tsx` and `DashboardLayout.tsx` are shared — same rule as `main.py`: single cleanup pass at the end assigns all routes and nav links rather than having agents collide on those two files.

| Track | What |
|---|---|
| Track 6 | Push to Jira button in `SprintPlannerPage.tsx` |
| Track 8 | Velocity Mirror UI controls |
| Track 10 | Exec Dashboard page + `useAppRole` hook |
| Track 12 | Developer Profile modal |
| Track 15 | Scope Cop panel in `SprintPlannerPage.tsx` |
| Track 18 | Dependency Radar page + Velocity Mirror alert wiring |
| Track 21 | Retrospective page + "View Retro" link on Velocity Mirror |

**Wave 4 gate:** All pages load without console errors. Role-gated nav links invisible to developer-role user. Each page's primary flow works end-to-end (generate plan → see scope panel; scan Jira → see dep list; generate retro → see three-section view).

---

### Wave 5 — Enrichment + Wiring (run after Wave 4)
Integration tracks that touch already-live code. Most likely to cause regressions.

**Before starting Tracks 22–23:** Read `apps/api/src/routers/sprint_brain.py` in its current state. Track 5 (Wave 3) added `POST /api/sprint-brain/push-to-jira` to this file — the Wave 5 agent must work from the Wave 3 output, not the original. Verify the existing generate endpoint returns a valid plan before making any change. Verify again after each edit.

| Track | What |
|---|---|
| Track 22 | Sprint Brain enrichment: `enrichmentStatus` + scope/dep warnings in plan response |
| Track 23 | Sprint Brain enrichment: retro pattern feedback + Claude prompt injection |
| Track 24 | Navigation wiring: routes, sidebar links, deep-link params |

**Wave 5 gate:** Full positive-path test for each enrichment source (seed dirty data → confirm correct `enrichmentStatus` value and non-empty warning list). Existing sprint plan generation still returns valid assignments. All cross-module deep links resolve.

---

## Critical Notes

> **`main.py` and `DashboardLayout.tsx` are merge traps.** Every wave that adds a router also needs a `main.py` line. Do not let multiple agents append to this file in parallel — assign a single "router registration" pass at the end of Wave 3, and a single "nav wiring" pass at the end of Wave 4. Same for `DashboardLayout.tsx`.

> **Tracks 22–23 are the highest-risk tracks in the entire plan.** They modify `generate_sprint_plan()`, which is the core revenue feature. Before editing: read `sprint_brain.py` top to bottom, run the existing generate flow once and confirm it works, then make the smallest possible change. The `enrichmentStatus` block must never cause the endpoint to error — wrap every enrichment query in `try/except` and default to `not_analyzed`/`not_scanned`/`no_data` on any DB failure.

> **The `enrichmentStatus` 3-state distinction is a contract, not a nicety.** `not_analyzed` ≠ `all_ready` ≠ `has_issues`. If these collapse to the same empty-list response, silent failures will be invisible. The positive-path verify steps in Tracks 22 and 23 are mandatory — they are the only tests that catch a field-name or filter mismatch before production.

> **Migration idempotency is non-negotiable.** Every migration must use `IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS`. Running `python migrate.py` twice on the same DB must produce no error. This is a live product — migrations may be applied to a DB that already has partial state.

---

## Track 0 — DB Foundations + Shared Utilities ✅ Complete
**Current state:** `SAEnum` params missing; migration `0005` not written; two private functions need extraction to shared utilities before Wave 2 service files are written. See `aos-contracts.md` Foundational Track 0 for full implementation spec.

- [x] Update `SAEnum(SprintStatus)` in `sprint.py` and `SAEnum(TicketStatus)` in `ticket.py` to include `values_callable=lambda obj: [e.name for e in obj]` — edit in place, do not recreate
- [x] Migration `0005_db_foundations.py`: unique constraint on `team_members(team_id, jira_account_id)`
- [x] New file `src/services/ai_client.py`: extract `get_anthropic_key(clerk_org_id, db)` from `routers/sprint_brain.py`; update `sprint_brain.py` to import from there
- [x] New file `src/services/health.py`: extract `compute_health_score(...)` from `routers/velocity.py`; update `velocity.py` to import from there
- [x] Verify: `python migrate.py` applies clean; duplicate insert raises `UniqueViolation`; `GET /api/velocity/stats` and `GET /api/sprint-brain/generate` still return valid responses after the refactors

## Track 1 — API Contracts ✅ Wave 0 Complete
**This track blocks everything.** No implementation track starts until every contract below is marked complete. Contracts live here, not in agent prompts — agents are given these contracts as input, not asked to invent them.

### MVP Contracts (A–F) — review spec
- [x] Read `federated-imagining-dream.md` in full for contracts A–F: Push to Jira (A), Velocity Stats extension (B), User Role (C/D), Exec Overview (E), Developer Profile (F)

### Contract G — Scope Cop
- [x] `POST /api/scope-cop/analyze` — Auth: `require_role("lead")`. Request: `{ teamId: string, ticketKeys: string[] }`. Response 200: `{ analyzedAt: string, results: [{ ticketKey, ticketTitle, readinessScore: number (0–100), status: "ready"|"needs_work"|"blocked", issues: string[], suggestions: string[] }], summary: { totalTickets, readyCount, needsWorkCount, blockedCount } }`. Response 402: no Anthropic key. Response 403: insufficient role. Response 404: team not found.
- [x] `GET /api/scope-cop/analyses/{team_id}` — Auth: `require_role("lead")`. Response 200: same shape as POST 200. Response 403: insufficient role. Response 404: no analyses exist for team.

### Contract H — Dependency Radar
- [x] `POST /api/dependency-radar/scan` — Auth: `require_role("lead")`. Request: `{ teamId: string }`. Response 200: `{ scannedAt: string, dependenciesFound: number, riskScore: number (0–100) }`. Response 402: no Jira connection. Response 404: team not found.
- [x] `GET /api/dependency-radar/team/{team_id}` — Auth: `require_role("lead")`. Response 200: `{ teamId: string, riskScore: number, dependencies: [DependencyItem] }` where `DependencyItem = { id, ticketKey, ticketTitle, blockedByKey: string|null, dependencyType: "blocks"|"is_blocked_by"|"external_service"|"cross_team", riskLevel: "high"|"medium"|"low", description: string|null, source: "jira"|"manual", resolvedAt: string|null, createdAt: string }`. Response 404: team not found.
- [x] `POST /api/dependency-radar/dependency` — Auth: `require_role("lead")`. Request: `{ teamId, ticketKey, ticketTitle, blockedByKey?, dependencyType, riskLevel, description? }`. Response 201: `DependencyItem`. Response 403: insufficient role. Response 404: team not found.
- [x] `PATCH /api/dependency-radar/dependency/{id}/resolve` — Auth: `require_role("lead")`. Response 200: `DependencyItem` with `resolvedAt` set. Response 403: insufficient role. Response 404: dependency not found.

### Contract I — Retrospective AI
- [x] `POST /api/retro/generate/{sprint_id}` — Auth: `require_role("lead")`. Response 200: `{ retroId, sprintId, sprintName, generatedAt, wentWell: string[], wentPoorly: string[], actionItems: [{ action: string, owner: string|null, priority: "high"|"medium"|"low" }], patterns: [{ patternType, description, occurrenceCount }], velocitySummary: { committed, delivered, completionRate } }`. Response 402: no Anthropic key. Response 403: insufficient role. Response 404: sprint not found. Response 422: sprint not completed.
- [x] `GET /api/retro/{sprint_id}` — Auth: `require_role("lead")`. Response 200: same shape as POST. Response 403: insufficient role. Response 404: retro not yet generated.
- [x] `GET /api/retro/patterns/{team_id}` — Auth: `require_role("lead")`. Response 200: `{ teamId: string, patterns: [{ id, patternType: "over_commitment"|"scope_creep"|"velocity_drop"|"blocker_recurrence"|"skill_gap", description, occurrenceCount, firstSeenAt: string|null, lastSeenAt: string|null, status: "active"|"resolved", affectedSprintNames: string[] }] }` (empty list when team exists but has no patterns). Response 403: insufficient role. Response 404: team not found.
- [x] `PATCH /api/retro/pattern/{pattern_id}/resolve` — Auth: `require_role("lead")`. Response 200: pattern item with `status: "resolved"`. Response 403: insufficient role. Response 404: pattern not found.

### Contract J — SprintPlanResponse Enrichment Extension
- [x] Four new fields added to the existing `SprintPlanResponse` (no breaking changes to existing fields): `scopeWarnings: [{ ticketId: string, status: "needs_work"|"blocked", issues: string[] }]`; `dependencyWarnings: [{ ticketId: string, riskLevel: "high", description: string|null }]`; `historicalWarnings: string[]`; `enrichmentStatus: { scopeCop: "not_analyzed"|"all_ready"|"has_issues", dependencyRadar: "not_scanned"|"no_risks"|"has_risks", retroPatterns: "no_data"|"no_active_patterns"|"has_patterns" }`
- [x] Confirm: all four fields are always present in the response (never omitted); all lists are empty arrays (not null) when no data; `enrichmentStatus` values are exact lowercase strings as specified — these become the TypeScript literal types in `types/sprint.ts`

## Track 2 — RBAC: DB + Model ✅ Complete
- [x] Add `AppRole` enum (DEVELOPER/LEAD/EXEC/ADMIN) to `models/developer.py` with `native_enum=False`
- [x] Add `app_role VARCHAR(20) DEFAULT 'developer'` column to `Developer` model
- [x] Migration `0006_add_app_role.py`: `ALTER TABLE developers ADD COLUMN IF NOT EXISTS app_role VARCHAR(20) NOT NULL DEFAULT 'developer'`
- [x] Export `AppRole` from `models/__init__.py`
- [x] Verify: migrate clean; `SELECT DISTINCT app_role FROM developers` returns `developer`

## Track 3 — RBAC: Auth Dependency + Endpoints ✅ Complete
- [x] New file `src/auth_roles.py`: `get_current_app_role()` + `require_role(minimum)` dependency factory
- [x] New file `src/routers/users.py`: `GET /api/users/me/role` + `POST /api/users/role`
- [x] Register `users_router` in `main.py`
- [x] Verify: GET returns `{ "appRole": "developer" }`; POST sets role; `require_role("exec")` returns 403 for dev user

## Track 4 — Jira Push: Client Methods ✅ Complete
- [x] Add `agile_base_url` property to `JiraClient` (`integrations/jira/client.py`)
- [x] Add `create_sprint()`, `move_issues_to_sprint()`, `assign_issue()` to `JiraClient`
- [x] New file `integrations/jira/push.py`: `resolve_jira_account_id()` — joins Developer→TeamMember via email
- [x] Verify: unit test resolver with matching and non-matching email; mock client methods assert correct URLs

## Track 5 — Jira Push: API Endpoint ✅ Complete
- [x] Add `PushToJiraRequest` model and `POST /api/sprint-brain/push-to-jira` to `routers/sprint_brain.py`
- [x] Logic: resolve team → check active sprint (409) → get JiraConnection (402) → create sprint → move issues → assign
- [x] Import `require_role`, `resolve_jira_account_id`, `_get_fresh_client`, `JiraConnection`
- [x] Verify: unknown teamId → 404; active sprint → 409; no Jira connection → 402; success → sprint visible in Jira

## Track 6 — Jira Push: Frontend ❌ Not started
- [ ] Add `PushToJiraResponse` type to `types/sprint.ts`
- [ ] Add `pushMutation` to `SprintPlannerPage.tsx` calling `POST /api/sprint-brain/push-to-jira`
- [ ] Render "Push to Jira" button (only when plan exists); 409/402 → amber banner; success → green banner + link
- [ ] Verify: button appears post-plan; error banners display correct messages; success banner shows ticket count

## Track 7 — Velocity Stats: API Extension ✅ Complete
**Current state:** `GET /api/velocity/stats` exists in `routers/velocity.py` with the `window` parameter. The `fromDate` param and its filter are the only missing pieces — do not rewrite the endpoint, only add the param and filter.

- [x] Add `from_date: date | None = Query(default=None, alias="fromDate")` to `get_velocity_stats()` in `routers/velocity.py`
- [x] Add `Sprint.end_date >= from_date` filter when param present
- [x] Verify: no param → unchanged; `?fromDate=2025-01-01` → filtered results; future valid date → empty results (not 422); malformed date (e.g. `?fromDate=notadate`) → 422

## Track 8 — Velocity Mirror: UI Controls ⚠️ Partial
**Current state:** `VelocityMirrorPage.tsx` and `VelocityStatsChart.tsx` exist and render the chart with hardcoded defaults. `VelocityControls.tsx` does not exist. `window`, `fromDate`, and `visibleMetrics` state are not present in `VelocityMirrorPage.tsx`. Do not recreate existing components — only add the controls file and lift the new state.

- [ ] New file `components/mirror/VelocityControls.tsx`: window slider (3–12), date picker, 3 metric checkboxes
- [ ] Update `VelocityStatsChart.tsx`: accept `window`, `fromDate`, `visibleMetrics` props; update query key/params
- [ ] Lift state in `VelocityMirrorPage.tsx`: add `window`, `fromDate`, `visibleMetrics` state; render `<VelocityControls>`
- [ ] Verify: slider/date/checkboxes each trigger chart refetch or re-render; clear date returns full history

## Track 9 — Exec Dashboard: API ✅ Complete
- [x] New file `src/routers/exec.py`: `GET /api/exec/sector-overview` with `require_role("exec")`
- [x] Response models: `TeamSummary`, `SectorOverviewResponse` (both with `alias_generator=to_camel`)
- [x] Logic: for each team — health score (import `compute_health_score` from `src/services/health.py`), velocity trend, completion rate, RAG status
- [x] Register `exec_router` in `main.py`
- [x] Verify: developer role → 403; exec role → 200; team with no data → zeros; sector score = mean of team scores

## Track 10 — Exec Dashboard: Frontend ❌ Not started
- [ ] New file `hooks/useAppRole.ts`: query `GET /api/users/me/role` with 5min stale time
- [ ] New file `components/exec/TeamHealthCard.tsx`: RAG badge, health score, trend arrow, completion bar, click→navigate
- [ ] New file `components/exec/SectorHealthBanner.tsx`: sector score, team count, status label
- [ ] New file `pages/ExecDashboardPage.tsx`: query sector overview; render banner + card grid; 403 → access denied
- [ ] New file `types/exec.ts`: `TeamSummary`, `SectorOverviewResponse` interfaces
- [ ] Add route `exec-dashboard` in `App.tsx`; nav link in `DashboardLayout.tsx` (exec/admin only)
- [ ] Verify: dev user sees no nav link; exec user sees page with correct cards; click card → velocity mirror

## Track 11 — Developer Profile: API ✅ Complete
- [x] New file `src/routers/developers.py`: `GET /api/developers/{developer_id}/profile` with `require_role("lead")`
- [x] Response model `DeveloperProfileResponse` with `alias_generator=to_camel`
- [x] Logic: avg_velocity, sprint_count, strong_ticket_types, domains, consistency_score from sprint data
- [x] Register `developers_router` in `main.py`
- [x] Verify: dev role → 403; lead role → 200; cross-org dev → 404; no sprint data → zeros/empty arrays

## Track 12 — Developer Profile: Frontend ⚠️ Partial
**Current state:** `DeveloperCapacityRow.tsx` exists and renders developer cards as plain divs with no click handlers. `DeveloperProfileModal.tsx` and `types/developer.ts` do not exist. Edit the existing component — do not recreate it.

- [ ] New file `types/developer.ts`: `DeveloperProfileResponse` interface
- [ ] New file `components/mirror/DeveloperProfileModal.tsx`: query profile, render stats modal, close on outside click
- [ ] Update `DeveloperCapacityRow.tsx`: make DevCards clickable; render `DeveloperProfileModal` on click
- [ ] Verify: click card → modal opens with API data; click outside → closes; 403 → access denied message

---

## Track 13 — Scope Cop: DB + Model ✅ Complete
**Goal:** Create `ticket_analyses` table. Stores per-ticket readiness scores from Claude analysis — one row per (team, ticket_key), upserted on re-analysis. No API yet. All new enums use `native_enum=False`.

- [x] New file `src/models/scope_cop.py`: `ScopeCopStatus` enum (`ready`, `needs_work`, `blocked`) with `native_enum=False`; `TicketAnalysis` mapped class with columns `id UUID PK`, `team_id UUID FK teams`, `ticket_key VARCHAR(50)`, `ticket_title TEXT`, `readiness_score INT` (0–100), `status VARCHAR(20)`, `issues JSONB` (string array), `suggestions JSONB` (string array), `analyzed_at TIMESTAMP DEFAULT now()`; unique constraint on `(team_id, ticket_key)` for upsert semantics
- [x] Export `ScopeCopStatus`, `TicketAnalysis` from `models/__init__.py`
- [x] Migration `0007_scope_cop_analyses.py`: `CREATE TABLE IF NOT EXISTS ticket_analyses ...`; `ADD CONSTRAINT IF NOT EXISTS uq_ticket_analysis UNIQUE (team_id, ticket_key)` — fully idempotent
- [x] Verify: `python migrate.py` applies `0007` cleanly; inserting the same `(team_id, ticket_key)` twice raises `UniqueViolation`; all three `ScopeCopStatus` values are insertable

## Track 14 — Scope Cop: Claude Service + API ✅ Complete
**Goal:** Claude evaluates ticket quality on four criteria and stores scored results. Two endpoints: one writes (analyze), one reads (fetch cached). Depends on Track 13.

- [x] New file `src/services/scope_cop.py`: `analyze_tickets(team_id, ticket_keys, jira_client, db)` — fetches full ticket detail (summary, description, story points, acceptance criteria field) from Jira per key; builds a structured prompt instructing Claude to score each ticket 0–100 on readiness using four criteria: (1) acceptance criteria present, (2) story point estimate set, (3) scope is bounded to one deliverable, (4) ownership is unambiguous; forces JSON output `[{ ticket_key, ticket_title, readiness_score, status, issues[], suggestions[] }]`; upserts each result to `ticket_analyses` via `ON CONFLICT (team_id, ticket_key) DO UPDATE SET ...`
- [x] New file `src/routers/scope_cop.py`: `POST /api/scope-cop/analyze` gated with `require_role("lead")` — accepts `{ teamId, ticketKeys[] }`, resolves team and Jira client, calls `analyze_tickets()`, returns `AnalyzeResponse` with `results[]` and `summary { totalTickets, readyCount, needsWorkCount, blockedCount }`; `GET /api/scope-cop/analyses/{team_id}` — returns latest stored analysis per ticket for the team with no Claude call; 404 if no analyses exist for team
- [x] `AnalyzeResponse` and `TicketAnalysisResult` use `ConfigDict(alias_generator=to_camel, populate_by_name=True)`
- [x] Register `scope_cop_router` in `main.py` with prefix `/api/scope-cop`
- [x] Verify: POST with 3 ticket keys → DB rows written, response contains per-ticket scores; GET returns same rows without re-calling Claude; POST with invalid `teamId` → 404; POST without lead role → 403

## Track 15 — Scope Cop: Frontend
**Goal:** Pre-plan analysis panel embedded in Sprint Planner page. Surfaces ticket readiness before plan generation — no new pages. Depends on Track 14.

- [ ] New file `types/scopeCop.ts`: `TicketAnalysisResult`, `AnalyzeResponse`, `ScopeCopSummary` interfaces matching API camelCase response shape
- [ ] New file `components/sprint/ScopeCopPanel.tsx`: accepts `response: AnalyzeResponse`; renders summary bar (Ready / Needs Work / Blocked counts as color-coded chips); expandable per-ticket list showing readiness score, status badge, issues list, and suggestions; "Re-analyze" button that re-fires the parent mutation
- [ ] Update `SprintPlannerPage.tsx`: add `scopeAnalysisMutation` calling `POST /api/scope-cop/analyze` with current backlog ticket keys; add "Analyze Scope" button above "Generate Plan" (visible when backlog is loaded); render `<ScopeCopPanel>` when mutation data exists; show amber warning banner "N tickets need work before planning" when `needsWorkCount > 0`
- [ ] Verify: "Analyze Scope" fires mutation and panel renders; re-analyze overwrites previous results; all-ready tickets show green summary; warning banner absent when all tickets are ready; "Generate Plan" still works independently of scope analysis

---

## Track 16 — Dependency Radar: DB + Model ✅ Complete
**Goal:** Create `dependencies` table. Stores per-ticket dependency records from both Jira auto-scan and manual entry. Tracks resolution status. No API yet.

- [x] New file `src/models/dependency_radar.py`: `DependencyType` enum (`blocks`, `is_blocked_by`, `external_service`, `cross_team`) and `RiskLevel` enum (`high`, `medium`, `low`) with `native_enum=False`; `Dependency` mapped class: `id UUID PK`, `team_id UUID FK teams`, `ticket_key VARCHAR(50)`, `ticket_title TEXT`, `blocked_by_key VARCHAR(50) NULL`, `dependency_type VARCHAR(30)`, `risk_level VARCHAR(10)`, `description TEXT NULL`, `source VARCHAR(10)` (`jira` | `manual`), `resolved_at TIMESTAMP NULL`, `created_at TIMESTAMP DEFAULT now()`
- [x] Export `DependencyType`, `RiskLevel`, `Dependency` from `models/__init__.py`
- [x] Migration `0008_dependencies.py`: `CREATE TABLE IF NOT EXISTS dependencies ...`; index on `(team_id, resolved_at)` for efficient active-only queries (`WHERE resolved_at IS NULL`); migration is idempotent
- [x] Verify: migration applies clean; insert one dep per `DependencyType`; `WHERE resolved_at IS NULL` returns only unresolved; both `source` values insertable

## Track 17 — Dependency Radar: Jira Scan + API ✅ Complete
**Goal:** Auto-detect dependencies from Jira issue links. Risk-score them. Expose CRUD + scan endpoints. Depends on Track 16 + Track 4 (JiraClient must exist).

- [x] Add `get_issue_links(issue_key)` to `JiraClient` (`integrations/jira/client.py`): `GET /rest/api/3/issue/{key}?fields=issuelinks,summary` — returns structured list of `{ type: str, inwardIssue: dict | None, outwardIssue: dict | None }`; raises `HTTPException(404)` if issue not found
- [x] New file `src/services/dependency_radar.py`: `scan_jira_dependencies(team_id, jira_client, db)` — fetches all non-completed backlog tickets for team; calls `get_issue_links` per ticket; maps Jira link type strings to `DependencyType` (`"blocks"` → `blocks`, `"is blocked by"` → `is_blocked_by`); applies risk rules: `is_blocked_by` with no target resolution date → `high`; links to external service or cross-team ticket → `medium`; `blocks` (team is the blocker) → `low`; upserts to `dependencies` with `source='jira'`; marks previously found Jira deps that no longer appear as resolved; also `compute_team_risk_score(deps: list[Dependency]) -> int` — weighted sum (high=3, medium=2, low=1) normalized to 0–100
- [x] New file `src/routers/dependency_radar.py`: four endpoints all gated with `require_role("lead")`: `POST /api/dependency-radar/scan` calls `scan_jira_dependencies()` and returns `{ scannedAt, dependenciesFound, riskScore }`; `GET /api/dependency-radar/team/{team_id}` returns all active deps plus aggregate `riskScore` (404 if team not found); `POST /api/dependency-radar/dependency` manually creates a dep with `source='manual'`; `PATCH /api/dependency-radar/dependency/{id}/resolve` sets `resolved_at = utcnow()`
- [x] All response models (`DependencyItem`, `ScanResponse`, `RadarResponse`) use `ConfigDict(alias_generator=to_camel, populate_by_name=True)`
- [x] Register `dependency_radar_router` in `main.py` with prefix `/api/dependency-radar`
- [x] Verify: scan with Jira connection → deps written to DB; GET returns them grouped with correct risk levels; PATCH resolve → `resolved_at` set and item excluded from subsequent GET; manual POST dep appears in GET; no Jira connection → 402; wrong team → 404

## Track 18 — Dependency Radar: Frontend
**Goal:** Standalone Dependency Radar page with risk-grouped dep list and resolve actions. High-risk deps surfaced as alerts in Velocity Mirror. All new nav is lead+ gated. Depends on Track 17.

- [ ] New file `types/dependencyRadar.ts`: `DependencyItem`, `RadarResponse`, `ScanResponse` interfaces matching API camelCase shape
- [ ] New file `components/radar/DependencyItem.tsx`: renders one dependency row — risk badge (red/amber/green), ticket key as Jira-link text, `dependencyType` chip, description text, "Resolve" button that calls `PATCH /api/dependency-radar/dependency/{id}/resolve` and optimistically removes the item from the list
- [ ] New file `pages/DependencyRadarPage.tsx`: query `GET /api/dependency-radar/team/{teamId}`; display aggregate risk score banner at top; three collapsible sections (High / Medium / Low) each rendering `<DependencyItem>` rows; "Scan Jira" button calling `POST /api/dependency-radar/scan` with loading state and result count toast; inline "Add Dependency" form for manual dep entry calling `POST /api/dependency-radar/dependency`; empty state message per section when no deps at that risk level
- [ ] Update `VelocityMirrorPage.tsx` alert feed: query `GET /api/dependency-radar/team/{teamId}` in parallel with existing data; render only high-risk active deps as non-dismissible alert rows with red left border and "View Radar" button navigating to `/dependency-radar`
- [ ] Add route `/dependency-radar` in `App.tsx`; add "Dependency Radar" nav link in `DashboardLayout.tsx` (lead+ only, grouped near Velocity Mirror)
- [ ] Verify: page renders deps grouped by risk level; resolve → item removed immediately (optimistic); Velocity Mirror alert feed shows only high-risk deps; "Scan Jira" updates the list; "Add Dependency" form creates and shows new dep; developer-role user sees no nav link

---

## Track 19 — Retro AI: DB + Models ✅ Complete
**Goal:** Create `retrospectives` (one per completed sprint) and `retro_patterns` (accumulates cross-sprint patterns) tables. `retro_patterns` is the persistence layer for the pattern-feedback loop that feeds back into Sprint Brain (Track 23). No API yet.

- [x] New file `src/models/retro.py`: `PatternType` enum (`over_commitment`, `scope_creep`, `velocity_drop`, `blocker_recurrence`, `skill_gap`) and `PatternStatus` enum (`active`, `resolved`) with `native_enum=False`; `Retrospective` mapped class: `id UUID PK`, `sprint_id UUID FK sprints UNIQUE`, `team_id UUID FK teams`, `generated_at TIMESTAMP`, `went_well JSONB`, `went_poorly JSONB`, `action_items JSONB` (array of `{ action, owner, priority }`), `velocity_summary JSONB`; `RetroPattern` mapped class: `id UUID PK`, `team_id UUID FK teams`, `pattern_type VARCHAR(30)`, `description TEXT`, `occurrence_count INT DEFAULT 1`, `first_seen_sprint_id UUID FK sprints NULL`, `last_seen_sprint_id UUID FK sprints NULL`, `status VARCHAR(10) DEFAULT 'active'`, `affected_sprint_names JSONB`
- [x] Export `PatternType`, `PatternStatus`, `Retrospective`, `RetroPattern` from `models/__init__.py`
- [x] Migration `0009_retro_ai.py`: `CREATE TABLE IF NOT EXISTS retrospectives ...`; `CREATE TABLE IF NOT EXISTS retro_patterns ...`; unique constraint on `retrospectives(sprint_id)`; composite index on `retro_patterns(team_id, status)` for active-pattern queries
- [x] Verify: `python migrate.py` applies `0009` cleanly; insert a retrospective; second insert for same sprint raises `UniqueViolation`; insert patterns of all five `PatternType` values; `WHERE status='active'` filter returns correct subset

## Track 20 — Retro AI: Claude Service + API ✅ Complete
**Goal:** Claude generates structured retrospective from completed sprint data. Pattern detection upserts recurring issues across sprints. Four endpoints. Depends on Track 19.

- [x] New file `src/services/retro_ai.py`: `generate_retrospective(sprint_id, team_id, db)` — loads sprint row, all sprint tickets, and per-developer velocity breakdown; computes `velocity_summary { committed, delivered, completionRate, overloadedDevs[], stalledTickets[] }`; sends structured prompt to Claude with sprint metrics instructing JSON output `{ wentWell[], wentPoorly[], actionItems[], detectedPatterns[] }` where each detected pattern includes a `patternType` from the `PatternType` enum; upserts `Retrospective` row (idempotent on `sprint_id`); calls `_upsert_patterns(team_id, detectedPatterns, sprint, db)` which increments `occurrence_count` on existing active patterns of the same type or inserts new ones with `occurrence_count=1` and updates `last_seen_sprint_id`; returns `RetroResponse` Pydantic model
- [x] New file `src/routers/retro.py`: four endpoints all gated with `require_role("lead")`: `POST /api/retro/generate/{sprint_id}` calls `generate_retrospective()` and returns `RetroResponse`; 422 if sprint status is not `COMPLETED`; idempotent (upserts, never duplicates); `GET /api/retro/{sprint_id}` returns stored retro or 404; `GET /api/retro/patterns/{team_id}` returns all patterns sorted by `occurrence_count DESC`; `PATCH /api/retro/pattern/{pattern_id}/resolve` sets `status = 'resolved'`
- [x] `RetroResponse`, `ActionItem`, `PatternResponse` use `ConfigDict(alias_generator=to_camel, populate_by_name=True)`
- [x] Register `retro_router` in `main.py` with prefix `/api/retro`
- [x] Verify: POST on completed sprint → Claude responds, retro stored, patterns upserted; POST again on same sprint → idempotent (no duplicate rows, `occurrence_count` not double-incremented); POST on active sprint → 422; GET returns stored retro; second generation with same pattern type → `occurrence_count` incremented to 2; PATCH resolve → `status = 'resolved'`

## Track 21 — Retro AI: Frontend
**Goal:** Retrospective page with sprint selector, three-section retro cards, action items, and pattern feed. Accessible from Velocity Mirror. All nav is lead+ gated. Depends on Track 20.

- [ ] New file `types/retro.ts`: `RetroResponse`, `ActionItem`, `PatternResponse`, `VelocitySummary` interfaces matching API camelCase shape
- [ ] New file `components/retro/RetroSection.tsx`: reusable card component — accepts `title`, `items: string[]`, `variant: 'positive' | 'negative' | 'neutral'`; renders colored left-border card (green / red / amber per variant); graceful empty state if items array is empty
- [ ] New file `components/retro/ActionItemList.tsx`: renders list of `ActionItem` objects — each row shows `action` text, `priority` chip (red=high/amber=medium/grey=low), `owner` label if present
- [ ] New file `components/retro/PatternFeed.tsx`: renders active `PatternResponse[]` sorted by `occurrenceCount` descending; each row shows `patternType` badge, `description`, occurrence count bubble, "Resolve" button calling `PATCH /api/retro/pattern/{id}/resolve` with optimistic removal from list
- [ ] New file `pages/RetrospectivePage.tsx`: completed-sprint selector dropdown querying existing sprint data (only `COMPLETED` sprints); "Generate Retro" button calling `POST /api/retro/generate/{sprintId}` — disabled if sprint already has a retro; on load queries `GET /api/retro/{sprintId}` and auto-populates if retro exists; renders three `<RetroSection>` cards (Went Well / Went Poorly / Action Items via `<ActionItemList>`) and `<PatternFeed>` below; loading skeleton during generation; accepts `?sprintId=` query param to pre-select sprint
- [ ] Update `VelocityMirrorPage.tsx`: add "View Retro" button in the sprint header row for each `COMPLETED` sprint — navigates to `/retrospective?sprintId={id}`
- [ ] Add route `/retrospective` in `App.tsx`; add "Retrospective" nav link in `DashboardLayout.tsx` (lead+ only)
- [ ] Verify: select completed sprint → generate → three sections and pattern feed render; select same sprint → loads from GET with no re-generation (Generate button disabled); pattern resolves → removed from feed; `?sprintId=` param pre-selects sprint; "View Retro" on Velocity Mirror navigates correctly; nav link absent for developer role

---

## Track 22 — Sprint Brain Enrichment: Scope Cop + Dependency Radar
**Goal:** Sprint plan response includes per-ticket scope readiness warnings, high-risk dependency flags, and an `enrichmentStatus` block that distinguishes "not yet run" from "ran and found nothing." Without `enrichmentStatus`, a schema mismatch silently looks like clean data. No new endpoints, no new DB tables. Depends on Tracks 13 and 16 (DB exists); safe when tables are empty.

- [ ] Extend `SprintPlanResponse` in `routers/sprint_brain.py` with: `scopeWarnings: list[dict]` (each item: `{ ticketId, status, issues[] }`); `dependencyWarnings: list[dict]` (each item: `{ ticketId, riskLevel, description }`); `enrichmentStatus: EnrichmentStatus` where `EnrichmentStatus` is a Pydantic model with fields `scopeCop: Literal["not_analyzed", "all_ready", "has_issues"]` and `dependencyRadar: Literal["not_scanned", "no_risks", "has_risks"]`
- [ ] In `generate_sprint_plan()` after building assignments: query `ticket_analyses` for all rows where `team_id = team.id` and `ticket_key IN (assigned keys)`; if no rows → `scopeCop="not_analyzed"`; rows found, none with `status != 'ready'` → `scopeCop="all_ready"`; rows found with flagged status → `scopeCop="has_issues"` and populate `scopeWarnings`; same 3-state logic for `dependencies` → `dependencyRadar` field; add one `logger.debug` line per source: `"[enrichment] scope_cop: %d checked, %d flagged"` and `"[enrichment] dep_radar: %d checked, %d high-risk"`
- [ ] Update `SprintPlannerPage.tsx`: render scope section based on `enrichmentStatus.scopeCop` — `not_analyzed` shows amber nudge "Scope not analyzed — Analyze Scope before planning"; `all_ready` shows green chip "All tickets scope-ready"; `has_issues` shows existing amber warning banners from `scopeWarnings`; same pattern for `dependencyRadar` — `not_scanned` shows "Dependencies not scanned", `no_risks` shows green chip "No dependency risks", `has_risks` shows red warning banners from `dependencyWarnings` with links to `/dependency-radar`
- [ ] Verify (positive-path — required): insert a `ticket_analysis` row with `status='needs_work'` for a ticket in the plan → response must have `enrichmentStatus.scopeCop="has_issues"` AND `scopeWarnings` non-empty; a schema mismatch (wrong field name or filter) will produce `"all_ready"` with empty warnings, which is a clearly wrong state
- [ ] Verify (empty-table path): with no rows in `ticket_analyses` → `enrichmentStatus.scopeCop="not_analyzed"`; with all rows `status='ready'` → `"all_ready"` with empty `scopeWarnings`; these three states must be distinct in every test

## Track 23 — Sprint Brain Enrichment: Retro Pattern Feedback
**Goal:** Sprint plan response includes active recurring failure patterns as historical context, with a `retroPatterns` enrichment status field. Claude's prompt context includes patterns so assignments account for known team weaknesses. Depends on Track 19 (DB exists); safe when table is empty.

- [ ] Extend `SprintPlanResponse` with: `historicalWarnings: list[str]` (pattern descriptions); add `retroPatterns: Literal["no_data", "no_active_patterns", "has_patterns"]` field to the `EnrichmentStatus` model from Track 22 — `no_data` means table empty for team, `no_active_patterns` means rows exist but none meet `occurrence_count >= 2` and `status='active'`, `has_patterns` means warnings populated
- [ ] In `generate_sprint_plan()`: query `retro_patterns` for team where `status = 'active'` and `occurrence_count >= 2`; no team rows at all → `retroPatterns="no_data"`; rows exist but none match filter → `retroPatterns="no_active_patterns"`; matches found → `retroPatterns="has_patterns"`, populate `historicalWarnings`, inject pattern list as "known recurring issues" context block in Claude prompt before ticket assignments; add `logger.debug("[enrichment] patterns: %d active for team")` log line
- [ ] Update `SprintPlannerPage.tsx`: render `historicalWarnings` in plan summary as collapsible "Recurring Issues" panel (indigo/purple left-border, visually distinct from amber scope and red dep warnings); collapse by default when more than two items; panel absent when `enrichmentStatus.retroPatterns` is `no_data` or `no_active_patterns`
- [ ] Verify (positive-path — required): insert two `retro_patterns` rows with `occurrence_count=2` and `status='active'` for the team → response must have `enrichmentStatus.retroPatterns="has_patterns"` AND `historicalWarnings` non-empty AND Claude prompt contains pattern text
- [ ] Verify (state distinction): team with no pattern rows → `no_data`; team with patterns but all `occurrence_count=1` → `no_active_patterns`; these must not collapse to the same empty-list response

## Track 24 — Navigation + Full Wiring
**Goal:** All new pages are reachable from the sidebar. Role visibility is globally enforced and consistent. All cross-module deep links resolve correctly. No logic or API changes — pure routing and nav.

- [ ] `App.tsx`: add routes `/dependency-radar` → `DependencyRadarPage`, `/retrospective` → `RetrospectivePage`; verify existing `/exec-dashboard` route still works; verify Sprint Planner and Velocity Mirror routes unchanged
- [ ] `DashboardLayout.tsx`: add nav group "Intelligence" with "Dependency Radar" (lead+) and "Retrospective" (lead+); keep "Exec Dashboard" in its own group gated at exec+; verify developer role sees only Sprint Planner + Velocity Mirror nav items
- [ ] `SprintPlannerPage.tsx`: verify the dep warning banner (Track 22) links correctly to `/dependency-radar`; verify "Analyze Scope" button (Track 15) is anchored in the page header; verify "Push to Jira" button (Track 6) still appears post-plan
- [ ] `VelocityMirrorPage.tsx`: verify "View Retro" deep-link (Track 21) resolves with `?sprintId=` param; verify dependency alert items (Track 18) link to `/dependency-radar`
- [ ] Verify: developer sees Sprint Planner + Velocity Mirror only; lead sees + Dependency Radar + Retrospective (4 items); exec sees all 5; navigating to `/dependency-radar` or `/retrospective` as developer-role user redirects to access-denied state or 403 page; `?sprintId=` param on `/retrospective` pre-selects the sprint in the dropdown

---

## End-to-End Verification Checklist

### Tracks 0–12 (MVP Core)
**Build status at start of execution:** Track 0 ⚠️ partial, Tracks 2–6 ❌, Track 7 ⚠️ partial, Track 8 ⚠️ partial, Tracks 9–11 ❌, Track 12 ⚠️ partial. Sprint Brain generate flow and Velocity Mirror base rendering are already live — do not regress them.

- [x] Migrations 0005 and 0006 both written and apply cleanly — neither exists yet
- [x] `SAEnum` declarations in `sprint.py` and `ticket.py` updated with `values_callable` — declarations exist, parameter is missing
- [x] `GET /api/users/me/role` returns correct role for seeded developers
- [x] Role guards: 403 for insufficient role on all gated endpoints
- [x] Sprint plan generated → Push to Jira → sprint visible in Jira with assignments
- [ ] Push with active sprint → 409 with correct UI banner
- [ ] Velocity Mirror: window, date, metric toggles all affect chart — controls do not yet exist
- [ ] Exec dashboard: hidden from non-exec users; shows correct RAG per team
- [ ] Developer profile modal: opens from capacity row, shows aggregated stats — `DeveloperCapacityRow.tsx` exists but cards are not yet clickable
- [x] All JSON responses use camelCase field names
- [x] All new enum values stored as lowercase VARCHAR
- [x] Existing `sprintstatus`/`ticketstatus` enums unchanged (UPPERCASE native)
- [x] Existing Sprint Brain generate endpoint still works after all Track 5/22/23 edits to `sprint_brain.py`

### Tracks 13–15 (Scope Cop)
- [x] Migrations 0007 applies clean on fresh DB
- [x] `POST /api/scope-cop/analyze` returns per-ticket readiness scores and stores to DB
- [x] `GET /api/scope-cop/analyses/{team_id}` returns stored results without re-calling Claude
- [ ] Sprint Planner: "Analyze Scope" panel renders summary bar and per-ticket breakdown
- [ ] Amber warning banner appears when any ticket has `needs_work` or `blocked` status

### Tracks 16–18 (Dependency Radar)
- [x] Migration 0008 applies clean
- [x] `POST /api/dependency-radar/scan` auto-detects Jira issue links and writes deps to DB
- [x] `PATCH /api/dependency-radar/dependency/{id}/resolve` sets `resolved_at`, GET excludes resolved
- [ ] Dependency Radar page: deps grouped by risk level; resolve removes item; "Add Dependency" form works
- [ ] Velocity Mirror alert feed shows high-risk deps with "View Radar" link

### Tracks 19–21 (Retrospective AI)
- [x] Migrations 0009 applies clean; `retrospectives(sprint_id)` uniqueness enforced
- [x] `POST /api/retro/generate/{sprint_id}` on completed sprint → retro stored + patterns upserted
- [x] `POST /api/retro/generate/{sprint_id}` on active sprint → 422
- [x] Second generation for same sprint → idempotent; pattern `occurrence_count` not doubled
- [ ] Retrospective page: three-section view renders; pattern feed shows active patterns; "Resolve" removes from feed
- [ ] "View Retro" button on Velocity Mirror navigates to correct sprint retro

### Tracks 22–24 (Cross-Module Wiring + Nav)
- [ ] `enrichmentStatus` in plan response has three distinct states per source — `not_analyzed` / `all_ready` / `has_issues` for scopeCop; `not_scanned` / `no_risks` / `has_risks` for depRadar; `no_data` / `no_active_patterns` / `has_patterns` for retroPatterns
- [ ] Positive-path test: seed dirty data per module → corresponding warning list is non-empty AND status field reflects correct state (not `all_ready` or `no_active_patterns`)
- [ ] Frontend renders three distinct UI states per enrichment source (nudge prompt / green clean chip / warning banners) — not just "show warnings or show nothing"
- [ ] Sprint plan for ticket with `needs_work` analysis → `scopeCop="has_issues"`, amber banners in plan UI
- [ ] Sprint plan for ticket with high-risk dep → `dependencyRadar="has_risks"`, red banners with link to `/dependency-radar`
- [ ] Team with 2+ active retro patterns → `retroPatterns="has_patterns"`, "Recurring Issues" panel visible in plan summary
- [ ] Claude prompt contains pattern context text when `retroPatterns="has_patterns"`
- [ ] Debug logs show enrichment row counts for every plan generation (visible in API logs)
- [ ] All new routes load; role gates enforced: dev=2 nav items, lead=4, exec=5
- [ ] `?sprintId=` query param on `/retrospective` pre-selects sprint
- [ ] No broken links across all cross-module navigation
