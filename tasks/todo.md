# Stage 2 — Multi-team, Multi-strategy Simulator Matrix

Full plan: `~/.claude/plans/lets-work-on-stage-quizzical-metcalfe.md`

## Goal
Measure how much Sprint Brain helps by running the same workload through 3 assignment strategies (random, omada, algorithm) across 5 team archetypes, repeated over multiple runs, then aggregating results.

Matrix per run: 5 archetypes × 3 strategies = 15 teams.

## Milestones

### M1 — Assigner foundation (done)
- [x] `src/assigners/base.py` — BaseAssigner, SprintContext, AssignmentResult, TicketAssignment
- [x] `src/assigners/random_assigner.py`
- [x] `src/assigners/algorithm_assigner.py` (load-balanced by story points placeholder)
- [x] `src/assigners/__init__.py` (factory)
- [x] `tests/test_assigners.py` — 14 new tests
- [x] `pytest tests/` → 39 passed (25 existing + 14 new)

Note: `run_team_simulation` extraction deferred to M2 — `simulation.py` stays untouched in M1 so stage 1 is unchanged.

### M2 — Single archetype, all 3 strategies (done)
- [x] `src/assigners/omada_assigner.py` (fallback path: degrade to random when team_id missing or plan empty)
- [x] Add `run_team_simulation` to `simulation.py` (new function; `run_simulation` untouched for stage-1 safety)
- [x] `src/matrix.py` — TeamRun, expand_matrix, run_matrix (sequential)
- [x] `src/team_factory.py` — stable_seed + materialize_team
- [x] `src/stage2_config.py` — Pydantic loaders
- [x] `config/archetypes/balanced.yaml`
- [x] `config/stage2.yaml`
- [x] `--stage 2 --smoke-test` + `--dry-run` in `main.py`
- [x] `tests/test_assigners.py` (+OmadaAssigner tests), `test_stage2_config.py`, `test_matrix.py`
- [ ] Smoke test passes end-to-end against local Omada **(USER ACTION — run command below)**

### M3 — All archetypes + aggregation (done)
- [x] `config/archetypes/{small,large,struggling,meeting_heavy}.yaml`
- [x] `src/aggregator.py` + `tests/test_aggregator.py`
- [x] `--aggregate` flag in main.py
- [x] `summary.csv` + `summary.md` (stdlib-only)
- [x] Dry-run confirms 15-cell matrix expansion

### M4 — Multi-run scale (largely landed via M2-M3)
- [x] `--runs N` outer loop (`run_matrix` iterates 1..runs)
- [x] Per-run subdirs `output/run_NNN/`
- [x] Run-aware seeding via `stable_seed(archetype, run_idx)`
- [x] Aggregator handles N>=1 (stddev populated when >1)
- [ ] Reset cleanup for matrix projects (deferred — for now use stage-1 `--reset --project-key SIM_BAL_RAND` per project)

### M5 — Real Omada multi-team (done)
- [x] `POST /api/teams` in `apps/api/src/routers/teams.py` (feature-flagged `allow_team_creation_via_api`)
- [x] `BoardSwitchRequest.team_id` (optional) — per-team `PUT /api/integrations/jira/board`
- [x] Feature flag: `local.yaml` true, `production.yaml` false
- [x] 7 apps/api tests covering idempotency, flag-off 403, foreign-org 404
- [x] `OmadaObserver.create_team(name, developers)` + extended `switch_board(team_id=)`
- [x] matrix.py setup creates per-team Omada team; falls back gracefully to shared team when flag off
- [x] 3 new simulator tests for the wrappers

### M6 — Parallel-by-archetype (done)
- [x] `parallel_teams` opt-in flag (default false) in stage2.yaml
- [x] When true, archetype groups run concurrently via `asyncio.gather`; strategies within an archetype stay sequential
- [x] Setup phase stays sequential (Jira rate-limit safe)
- [x] `JiraDriver(audit_log_dir=...)` and `OmadaObserver(audit_log_dir=...)` constructor params
- [x] matrix.py passes per-team `tr.output_dir` so each team has its own audit logs
- [x] Stage-1 callers unchanged (backward-compat default to module-level paths)
- [x] 5 new tests covering parallel default + audit-dir override/default for both drivers

### How-to-run doc (done)
- [x] `omada-simulator/docs/STAGE2_HOWTO.md` — 12 sections: prereqs, smoke test, aggregation, full matrix, multi-run, output layout, cleanup, sprint length, adding archetypes/strategies, troubleshooting, architecture reference

## Notes / decisions
- Omada team-creation gap is M5 work. M1-M4 ship with shared Omada team (omada column is single-team approximation, documented in summary.md).
- Algorithm strategy ships as load-balanced-by-story-points placeholder behind swap-in `assign()` interface.
- Sequential team execution until M6 to dodge Jira rate limits (10 req/sec org-wide).
- `pick_sprint_tickets` (ticket_generator.py:123) stays for stage-1 backward compat; stage 2 uses `BaseAssigner.select_tickets` (dev-less equivalent).
- Same-pool fairness: `stable_seed(archetype, run_idx)` shared across the 3 strategies so all face identical tickets per (archetype, run).

## Review

**M1-M6 + how-to-run doc landed in this session.** 89 tests passing in omada-simulator (39 baseline + 50 new). 7 new tests in apps/api.

New files:
- `src/assigners/{__init__.py,base.py,random_assigner.py,algorithm_assigner.py,omada_assigner.py}`
- `src/{matrix.py,team_factory.py,stage2_config.py,aggregator.py}`
- `config/stage2.yaml` + `config/archetypes/{balanced,small,large,struggling,meeting_heavy}.yaml`
- `tests/{test_assigners.py,test_stage2_config.py,test_matrix.py,test_aggregator.py}`

Modified:
- `src/simulation.py` — added `run_team_simulation` (run_simulation untouched)
- `src/main.py` — added `--stage 2` family: `--simulate`, `--smoke-test`, `--aggregate`, `--archetype`, `--strategy`, `--runs`
- `src/ticket_generator.py` — added optional `seed` param to `generate_ticket_pool`

What works (verified by `--dry-run`):
- Full matrix expands to 15 teams (5 archetypes × 3 strategies) with correct pool sizes per archetype
- Same `run_seed` shared across the 3 strategies of one archetype (fairness invariant)
- Project keys: `SIM_<ARCH3>_<STRAT4>` (SIM_STR_OMAD, SIM_MTG_ALGO, ...)
- `--smoke-test` constrains to 1 archetype × 3 strategies × 1 sprint × 1 run
- `--aggregate` reads `output/run_*/*/simulation_results.json` and produces `output/aggregate/{summary.csv,summary.md}`

Deferred:
- **M5**: `POST /api/teams` in apps/api so each matrix cell gets its own Omada team. Until then, all 15 teams share one Omada team — the `omada` strategy column in `summary.md` reflects whichever board Omada was pointed at last (sequential execution makes this work for the active sprint).
- **M6**: Parallel-by-archetype execution. Sequential is the current safe path (Jira 10 req/sec org-wide rate limit).
- Reset/cleanup helper for matrix projects (use stage-1 `--reset --project-key <key>` per project for now).

Next: smoke test against running local Omada.

---

## Session: 2026-05-20 — Four bugs distorting the matrix report

After publishing `output/aggregate/summary.html` showing Omada underperforming algorithm on 4/5 archetypes (and badly on `large`), investigation found the data was misleading. Four bugs landed; full matrix re-run pending.

### Bugs found

- **Bug A — `omada_team_id` clobbered.** `simulation.py:612` called `omada.resolve_team_id()` unconditionally, throwing away the per-team UUID `_simulate_team` had just resolved via M5's `POST /api/teams`. Every omada cell planned against the org's shared primary team. SprintBrain plans showed *"Only one developer is eligible"* — confirming the bigger archetypes (large with 8 devs, struggling with 4) were planning against the wrong roster. Round-robin fallback absorbed the dropped tickets, so Omada degraded toward random-with-overhead. Fixed: only `resolve_team_id()` when `omada_team_id` is None.
- **Bug B — `push_to_jira` 409s on sprint ≥ 2.** `OmadaAssigner.push_plan_to_jira` creates a *second* Jira sprint (the push handler always calls `client.create_sprint`). The simulator only closed its own Jira sprint, leaving the push's sprint OPEN — so the corresponding Omada Sprint row stayed ACTIVE and sprint N+1's push returned 409 ("active sprint in progress"). Evidence: every `sprint_N_push.json` with `plan_ok=true` was `{}`. Fixed: after `jira.close_sprint(sprint_id)`, also close `assignment_result.push_response['jiraSprintId']` if different.
- **Bug C — Audit log only captured setup events.** `simulation.py:610` constructed `OmadaObserver` without `audit_log_dir`, so per-sprint HTTP calls (sync/plan/push/retro) were unlogged. Diagnosing Bug A required reading code; with proper logging it'd have been a grep. Fixed: pass `audit_log_dir=output_dir`.
- **Bug D — `sync_jira_team` never syncs backlog issues.** Surfaced only after Bug A was fixed: fresh per-team Omada teams returned `422 "No candidate tickets found for this team"` on plan. Root cause: `sync_jira_team` iterates Jira sprints and pulls each sprint's issues, but backlog issues (sprint = EMPTY) never reach Omada DB. The org primary team only worked because earlier runs had left tickets in completed-sprint state. Fixed in `apps/api/src/integrations/jira/sync.py`: added `_upsert_backlog_issues` + JQL `sprint is EMPTY` fetch at end of `sync_jira_team`. This benefits real first-time customers too.
- **Bug E (infra, not code) — Celery worker not running.** `omada.trigger_sync` returned 200 (queued) but with no worker, 153 tasks sat in Redis indefinitely. `wait_for_sync` timed out and the sim proceeded anyway. Documented in `tasks/lessons.md`. Worker started via `cd apps/api && .venv/bin/celery -A src.worker worker --loglevel=info --pool=solo`.

### Other changes

- **Bigger samples.** `total_sprints: 3 → 5` across all five archetype yamls. `--runs 5` planned (was 1).
- **`parallel_teams: true`** in `omada-simulator/config/stage2.yaml` (was false). Archetype groups run concurrently; the 3 strategies inside each archetype stay sequential because they share a Jira project/board switch.
- **New: `src/report_html.py`** (735 lines, stdlib only) — replaces hand-edited `summary.html` with a data-driven renderer. Reads `summary.csv`, computes KPIs/insights, renders the same Chart.js layout. Verified against current stale CSV (15 rows). `main.py --aggregate` now prints the invocation hint.
- **Test deltas.** `test_parallel_teams_default_false` → `test_parallel_teams_default_true` (and matching assert). 84/89 pass; 5 pre-existing failures are project-key format mismatches in WIP tests (`SIM_BAL_OMAD` vs `SIMBALOMAD` — Jira project keys can't contain underscores).
- **`tasks/lessons.md`** extended with 5 new lessons (subagent state leakage; backlog sync gap; Celery silently dropping tasks; half-instrumented observer; defensive-fallback-before-honor-input).

### Files touched

| File | Change |
|------|--------|
| `omada-simulator/src/simulation.py` | Fix A (line ~612), Fix B (line ~772), Fix C (line ~610) |
| `apps/api/src/integrations/jira/sync.py` | Fix D — `_upsert_backlog_issues` + backlog fetch after sprint loop |
| `omada-simulator/config/archetypes/{balanced,small,large,meeting_heavy,struggling}.yaml` | `total_sprints: 3 → 5` |
| `omada-simulator/config/stage2.yaml` | `parallel_teams: false → true` |
| `omada-simulator/src/report_html.py` | NEW — data-driven `summary.html` renderer |
| `omada-simulator/src/main.py` | `--aggregate` prints renderer invocation hint |
| `omada-simulator/tests/{test_matrix.py,test_stage2_config.py}` | Updated `parallel_teams` assertion |
| `tasks/lessons.md` | Five new lessons |

### Results (--runs 1, sequential)

Five completed fixes + one architecture change (parallel_teams flipped back to false after parallel mode caused Jira/Anthropic contention that disproportionately hurt the omada strategy):

| Bug | Status |
|-----|--------|
| A: `omada_team_id` clobber (simulation.py:612) | fixed |
| B: push 409s on sprint ≥ 2 (FUTURE→ACTIVE→CLOSED transition) | fixed |
| C: simulation-time OmadaObserver missing `audit_log_dir` | fixed |
| D: `sync_jira_team` doesn't sync backlog issues | fixed in apps/api |
| E: dev-only seed-tickets endpoint (bypass stale-OAuth-token Jira sync) | new endpoint |

Plus: switched SprintBrain `_MODEL` from `claude-opus-4-7` → `claude-sonnet-4-6` (Opus was timing out plan calls at 60s+ with full dev rosters).

### Completion rates (12 clean cells of 15 — see "Reliability notes" below)

| archetype | algorithm | omada | random | omada vs old report |
|-----------|-----------|-------|--------|---------------------|
| small | 72% | **76%** ✓ | 73% | was 70% (now wins) |
| large | 47% | **50%** ✓ | 47% | was 33% (was -22pp, now +3pp) |
| balanced | **35%** | 27% | 28% | was 40% (still loses) |
| struggling | 0%* | 18% | **24%** | was 29% (still loses) |
| meeting_heavy | **26%** | 0%* | 0%* | was 47% (unreliable cells) |

✓ = omada wins. * = cell had Jira `sync_ok_pct = 0%` (corrupted by API issues late in run; see Reliability).

### The headline

The OLD report's "Omada catastrophically loses on large" finding was an artifact of the simulator-side `omada_team_id` clobber sending all omada cells to the org primary team. After Fix A, **large/omada flipped from 33% → 50%** — Omada now wins on the team-size axis where the old report claimed its worst defeat.

Omada wins clearly on `small` and `large`, loses on `balanced`, and the other two archetypes are inconclusive (see below). Spillover follows the same shape: omada is best on `small` (2.8 vs 3.4) and `large` (14.4 vs 16.4+).

### Reliability notes

3 of 15 cells had `sync_ok_pct = 0%` in integration health — meeting_heavy/random, meeting_heavy/omada, and struggling/algorithm. These cells ran near the end of the ~3.5h sequential run; the most likely explanation is transient Jira API failures or Anthropic 503s during that window. The 12 clean cells gave us a coherent picture; the 3 bad cells produced 0% completion across all sprints (so they're easy to filter).

`plan_ok_pct` looks like:
- large/omada: 100% (5/5 sprints — clean signal)
- small/omada: 100% (5/5 — clean signal)
- balanced/omada: 60% (3/5 — Anthropic 503s on 2 sprints, fell back to random)
- struggling/omada: 20% (1/5 — same)
- meeting_heavy/omada: 0% (entire cell corrupted)

So Omada's signal is strongest on the two archetypes where plan_ok was 100% — and **on both of those, omada beat algorithm and random**.

### Files generated

- `omada-simulator/output/aggregate/summary.csv` — raw data
- `omada-simulator/output/aggregate/summary.md` — markdown report
- `omada-simulator/output/aggregate/summary.html` — Chart.js dashboard (auto-generated by new `src/report_html.py`)
- `omada-simulator/output/run_001/*/simulation_results.json` — per-cell raw

### Next-iteration recommendations

- Re-run with `--runs 3` sequential to add std-dev signal (current report is n=1)
- Add Anthropic retry/circuit-breaker around `_get_candidate_tickets` so transient 503s don't drop plan_ok_pct
- Investigate the 3 unreliable cells: check apps/api logs at the time window meeting_heavy/struggling ran
- Bump archetype `ticket_pool_size` so sprint 5 doesn't run out (current pools cover ~4 sprints only)
- Wire `retro_ok_pct` — every cell shows 0%, suggesting retro generation is broken end-to-end

---


# # Initiative A — Identifier Associations + Skill Intensity Routing

Status: **planning — pending verification before implementation**

## Goal

Bridge the gap between the abstract stack labels the scrum master selects in onboarding (e.g. `SQL`, `Java/Spring Boot`) and the concrete identifiers that actually appear in ticket text (e.g. `dbo.tile_metrics`, `ms-service`). Use the resulting team-specific glossary to produce per-ticket **skill-intensity vectors**, then route assignments in Sprint Brain by matching those vectors against per-developer skill ratings.

## Why

Sprint Brain today guesses `required_skills` from ticket prose alone (`apps/api/src/services/sprint_brain.py`), and the `velocity_breakdown` it sends to Claude is a stubbed single-row average. Developer fields `domain_strengths`, `seniority`, and `meeting_hours_bucket` are captured but ignored. Scope Cop has no way to know whether a ticket actually touches the team's stack. Identifier associations + intensity vectors give all three features real grounding.

## Architecture

```
Onboarding ── scrum master picks stack ─────┐
                                            ▼
Jira history import ─► bootstrap scan ─► team_identifiers table
                       (one Claude pass)        │
                                                ▼
                       per-ticket intensity ─► ticket_skill_analyses
                       (regex match + verb       │
                        context + effort)        ▼
                                          Sprint Brain prompt
                                          Scope Cop 5th criterion
                                                ▲
                            incremental refresh │
                            (sprint-close hook) │
```

## Data model

New tables (alembic migration 0017):

**`team_identifiers`**
- `id` uuid PK
- `team_id` uuid FK → teams
- `token` text (raw — `dbo.tile_metrics`)
- `normalized_token` text (lowercase, indexed for fuzzy lookup)
- `skill` text (one of team.tech_stack labels)
- `domain` text nullable (`backend` / `frontend` / `infra` / `data`)
- `confidence` float 0–1
- `source` enum (`epic`, `ticket_description`, `ticket_title`, `label`, `component`)
- `occurrence_count` int
- `first_seen_at`, `last_seen_at` timestamps
- UNIQUE (team_id, token)
- INDEX (team_id, normalized_token)

**`ticket_skill_analyses`**
- `id` uuid PK
- `ticket_id` uuid FK
- `skill_vector` jsonb (`{"SQL": 0.8, "Java": 0.3}`)
- `domain_vector` jsonb (`{"backend": 0.9, "frontend": 0.1}`)
- `matched_identifiers` jsonb array (tokens that hit)
- `analyzed_at` timestamp
- UNIQUE (ticket_id)

**Alter `developers`**
- Add `skill_ratings` jsonb (`{"SQL": 0.9, "Java": 0.6}`, 0–1 scale)
- Keep existing `domain_strengths` for back-compat; deprecate once UI migrates

## Milestones

### M1 — Extraction foundation (no LLM)
- [ ] Alembic 0017: create `team_identifiers`, `ticket_skill_analyses`; add `developers.skill_ratings`
- [ ] `src/models/identifier.py` — TeamIdentifier, TicketSkillAnalysis ORM models
- [ ] `src/services/identifier_extraction.py` — regex tokenizer (`schema.table`, `kebab-case-service`, `snake_case`, `CamelCase` with ≥2 segments, path-like)
- [ ] `src/services/identifier_extraction.py` — normalizer (lowercase, strip punctuation)
- [ ] Tests: extraction edge cases (single words filtered, multi-segment kept, punctuation handled)

### M2 — Bootstrap classifier (one Claude pass)
- [ ] `src/services/identifier_classifier.py` — `classify_identifiers(tokens, team_stack, anthropic_key) → list[ClassifiedIdentifier]` (Claude tool_use, structured output)
- [ ] `src/routers/identifiers.py` — POST `/api/identifiers/scan` (lead role); pulls closed-sprint tickets + epics for team, extracts tokens, batches to classifier, upserts to `team_identifiers`
- [ ] GET `/api/identifiers/{team_id}` — list
- [ ] PATCH `/api/identifiers/{id}` — manual correction
- [ ] DELETE `/api/identifiers/{id}` — remove false positive
- [ ] Tests: classifier prompt builds correctly, upsert behaves, scan handles empty history

### M3 — Per-ticket intensity inference
- [ ] `src/services/skill_intensity.py` — `compute_intensity(ticket, identifiers) → SkillVector`
  - Identifier density (count of matches per skill)
  - Verb context (verbs preceding identifier: `design|optimize|rewrite` → high; `read|fetch|select` → low) — small verb lookup table
  - Effort multiplier (low/medium/high from existing complexity pass)
- [ ] Cache results in `ticket_skill_analyses`
- [ ] Tests: synthetic ticket → expected vector

### M4 — Sprint Brain integration
- [ ] Extend Onboarding `AddMembersStep` / `MemberForm` to capture `skill_ratings` per developer
- [ ] `src/services/sprint_brain.py::_get_developer_profiles` — include `skill_ratings`
- [ ] Compute real `velocity_breakdown` — group past tickets by skill (via `ticket_skill_analyses`), aggregate per-skill points per developer
- [ ] Inject `skill_vector` into assignment prompt per ticket
- [ ] Update `_SPRINT_PLAN_TOOL` schema: assignments include `skill_match_reasoning` field
- [ ] Routing rules (in prompt + as warnings):
  - All-low vector → unconstrained
  - Single-high → narrow to qualified devs; warn if none rated ≥ 0.6
  - Multi-high → assign to top combined-rating dev or pair-program candidate

### M5 — Scope Cop fifth criterion
- [ ] `src/services/scope_cop.py` — extend `_SCOPE_COP_TOOL` with `stack_alignment` score
- [ ] Pass `matched_identifiers` count to Scope Cop prompt
- [ ] Tickets with zero identifier matches → flag as `needs_work` even if other criteria pass

### M6 — UI surfaces
- [ ] Settings page: "Team Glossary" — table of known identifiers, inline edit skill/domain, bulk delete
- [ ] Sprint Planner: per-ticket required-skills pills (color-coded by intensity)
- [ ] Sprint Planner ticket detail: "matched identifiers" list with link to glossary
- [ ] Onboarding: trigger scan automatically after `import_jira_sprint_history` completes; show progress; no extra wizard step

### M7 — Incremental refresh
- [ ] Background hook in sprint-close path: scan new tickets since last refresh, classify new tokens only (skip known)
- [ ] Age-out: identifiers not seen in 6 months get `confidence *= 0.9` per refresh; pruned at < 0.1
- [ ] Tests: refresh idempotency

## Open questions

1. **Initial `skill_ratings` source.** Self-declared in onboarding? Inferred from past tickets in `ticket_skill_analyses` once M3 lands? Both — self-declare in M4, then auto-recalibrate after one sprint?
2. **LLM throughput for bootstrap scan.** A team with 500 closed tickets could yield thousands of candidate tokens. Cap at top-N most-frequent? Batch in chunks of 200 with explicit batching protocol?
3. **Token extraction precision.** Generic `CamelCase` (e.g., `TaskList`) is noisy — require ≥2 segments or explicit punctuation (`.`, `_`, `-`, `/`) to qualify as identifier?
4. **Cross-team identifier overlap.** Strictly team-scoped; no global table. Worth revisiting if multi-team orgs share repos.
5. **Manual review of first scan.** Auto-persist with confidence, or require lead to approve the first batch? Default: auto-persist + surface low-confidence rows in the Glossary UI for review.

## Verification gates

Before merging M4 (the user-visible change):
- [ ] Run omada-simulator on a balanced archetype with intensity routing enabled — confirm `plan_ok_pct` ≥ baseline
- [ ] Spot-check 5 real assignments: does the cited skill_match_reasoning hold up under inspection?
- [ ] No regression on Scope Cop `analyzed_at` cache behavior


### M8 — Override capture + feedback loop

Lands after M4 (which is what creates an overridable plan).

**Principle:** AI proposes changes to `skill_ratings`, `team_identifiers`, and `domain_strengths` based on override *patterns*; lead approves. No silent mutation.

#### M8a — Capture (low-cost, useful even without AI integration)
- [ ] Alembic 0018: create `sprint_plan_overrides` table
  - `id` uuid PK
  - `sprint_id` uuid FK
  - `ticket_id` uuid FK
  - `action` enum (`reassign`, `remove`, `add`)
  - `original_developer_id` uuid nullable
  - `new_developer_id` uuid nullable
  - `reason_code` enum nullable (`skill_fit`, `capacity`, `mentorship`, `pto`, `priority_change`, `other`)
  - `reason_text` text nullable (free-form)
  - `created_by` uuid (clerk user)
  - `created_at` timestamp
  - INDEX (sprint_id), INDEX (ticket_id, new_developer_id)
- [ ] `src/models/sprint_plan_override.py` ORM model
- [ ] `src/routers/sprints.py` — patch the assignment-edit endpoint to write an override row on every diff
- [ ] UI: when lead reassigns/removes/adds in Sprint Planner, show optional reason chip picker (skippable, defaults to `null` — never block the save)
- [ ] Tests: override row created on each action type; reason optional

#### M8b — In-context feedback to next plan (cheap, immediate)
- [ ] `src/services/sprint_brain.py::_build_assignment_message` — append a "Previous Sprint Overrides" section pulling the last sprint's `sprint_plan_overrides` for this team
- [ ] Format: `"PROJ-123 reassigned Alice → Bob (reason: skill_fit)"` — include only the last 1–2 sprints to keep tokens bounded
- [ ] Update `_SYSTEM_PROMPT` to instruct Claude to factor in recurring override patterns
- [ ] Tests: prompt includes override context; empty overrides → section omitted

#### M8c — Pattern-based recalibration proposals (the real learning)
- [ ] `src/services/override_analyzer.py` — `detect_patterns(team_id, db) → list[RecalibrationProposal]`
  - For each (developer, skill) pair: count `skill_fit`-tagged reassignments *away from* that dev on tickets where their `skill_vector[skill]` > 0.5
  - Threshold: ≥3 same-direction overrides in trailing 90 days → emit proposal
  - Proposal payload: `{developer_id, skill, current_rating, suggested_rating, evidence: list[override_id]}`
- [ ] Also detect identifier misclassification: if tickets containing identifier X are repeatedly reassigned with reason `skill_fit`, propose reclassifying the identifier
- [ ] New table `recalibration_proposals` — status enum (`pending`, `approved`, `dismissed`)
- [ ] `src/routers/identifiers.py` (or new `recalibration.py`) — GET pending, POST approve/dismiss
- [ ] UI: Settings → "Calibration Suggestions" card with evidence links to the specific overrides
- [ ] On approval: mutate `developers.skill_ratings` or `team_identifiers.skill`; record audit row
- [ ] Tests: 2 overrides → no proposal; 3 same-direction → proposal emitted; dismiss → no re-prompt for 30 days

#### M8d — Plan-quality telemetry (the system-level metric)
- [ ] `src/services/plan_quality.py` — compute per-plan override_rate = (override_count / total_assignments)
- [ ] Persist on Sprint row: `plan_override_rate`, `plan_overrides_by_reason` jsonb
- [ ] Exec Dashboard chart: trailing 8-sprint override rate per team — the *real* signal for whether Sprint Brain is getting better
- [ ] Alert threshold: any sprint with `override_rate > 0.5` flagged in Exec view

## Open questions (M8)

1. **Reason chip UX.** Required vs optional? Optional makes adoption easier but kills the recalibration signal if leads skip. Compromise: optional, but show a one-time tooltip ("Add a reason to help Sprint Brain learn") on first 3 overrides.
2. **Recalibration aggression.** 3 overrides in 90 days is conservative. Tune after M8c ships — too few proposals = no learning; too many = lead fatigue and dismissals.
3. **Override-influenced velocity.** When Alice was assigned PROJ-123 but Bob actually did the work, whose velocity does the ticket count toward? Currently `Ticket.assignee_id` is the source of truth at sprint close. Confirm the override flow updates `assignee_id` (not just the plan record), or we double-count.
4. **Identifier misclassification proposals.** Same threshold (3 events)? Or require lead to explicitly tag the override as "this ticket isn't really about \<identifier\>"? The latter is more precise but adds UI friction.

---

# Initiative B — Inline Ticket Refinement

Status: **planning — pending verification before implementation**

## Goal

Turn Scope Cop from advisory into closed-loop. When a ticket scores `needs_work` or `blocked`, the lead opens an inline drawer showing the original Jira issue side-by-side with an AI-suggested revision (diff-highlighted), edits as needed, and pushes the corrected version back to Jira — replacing the faulty ticket in place. No round-trip through Jira's UI required.

Sibling to the identifier-associations initiative above, not dependent on it.

## Why

Scope Cop today (`apps/api/src/services/scope_cop.py`) returns a readiness score plus `issues` and `suggestions` lists. Users read them, switch context to Jira, manually rewrite. Most don't bother. The score is information without action. Inline refinement closes the loop: the AI produces the *content* of the fix, not just a description of the problem.

## Architecture

```
Sprint Brain generates plan
        │
        ▼
B0: auto-run Scope Cop on assigned ticket keys (extended schema: issues,
    suggestions, suggested_revision { title, description, AC, story_points })
        │
        ▼
ticket_analyses populated for every assigned ticket
        │
        ▼
┌────────────────────────────────────────────────────────────────┐
│  Plan Review Modal (B8)  —  TRIAGE MODE                        │
│  ┌────────────┬─────────────────────────────┬──────────────┐   │
│  │ Left rail  │ Center: editor pane (B5)    │ Right rail   │   │
│  │ all assign │  original | suggested+edit  │ assignee     │   │
│  │ status pill│  diff highlight             │ velocity     │   │
│  │ + avatar   │                             │ reasoning    │   │
│  └────────────┴─────────────────────────────┴──────────────┘   │
│  Bottom-right: [ Review and Commit ] button                    │
└──────────────────────────┬─────────────────────────────────────┘
                           │ (mandatory — no bypass)
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  Sign-off Carousel (B9)                                        │
│  Full-screen takeover, one ticket at a time, progress 4 / 12.  │
│  Per ticket: original + suggested + assignment + reasoning.    │
│  Actions: [Approve] → next  /  [Go back to edit] → return to   │
│  B8 with this ticket selected (prior approvals preserved).     │
│  Bulk-approve: [Approve next 5] for streaks.                   │
└──────────────────────────┬─────────────────────────────────────┘
                           │ (all approved)
                           ▼
B10: batched Jira push (assign + sprint custom field, atomic-ish)
        + ticket_revisions audit rows with approved_at/approved_by
```

## Milestones

### B0 — Wire Sprint Brain → Scope Cop pipeline (prerequisite for the modal UX)
- [ ] After `_extract_plan` returns assignments in `src/routers/sprint_brain.py`, call `scope_cop.analyze_tickets(team_id, assigned_keys, jira_client, db)` before `_build_enrichment`
- [ ] Wrap in try/except — Scope Cop failure (rate limit, API error) must not block plan generation; log and continue
- [ ] Add `scope_cop_ran_at: datetime | None` to the plan response so the modal knows the freshness of analyses it's reading
- [ ] Tests: planning generates analyses for all assigned tickets; on Scope Cop failure, plan still returns

### B1 — Scope Cop generates suggested revisions
- [ ] Extend `_SCOPE_COP_TOOL` schema with `suggested_revision` object: `{title, description, acceptance_criteria[], story_points}`
- [ ] Update `_SYSTEM_PROMPT` — instruct Claude to write the actual fix content per criterion, not just describe what's missing
- [ ] Migration 0020: add `suggested_revision` jsonb column to `ticket_analyses` (bumped from 0019 — Initiative A claimed 0017–0019)
- [ ] Update `TicketAnalysisResult` Pydantic model + `AnalyzeResponse`
- [ ] Tests: fixture ticket with missing AC → response contains plausible AC strings

### B2 — Jira write integration
- [ ] Audit `apps/api/src/integrations/jira/oauth.py` — confirm whether current scopes include `write:jira-work`
- [ ] If scope upgrade needed: add re-auth prompt for existing `JiraConnection` rows; new flow requests upgraded scope
- [ ] `JiraClient.update_issue(key, fields)` method (PUT `/rest/api/3/issue/{key}`)
- [ ] Plain-text description for v1 (let Jira parse); ADF round-tripping deferred to v2
- [ ] Tests against Jira sandbox: title-only update, description update, story-point update, AC field update

### B3 — Conflict detection + audit trail
- [ ] Capture `fields.updated` timestamp when drawer opens (already in API response, just expose it)
- [ ] At PATCH time: re-fetch issue, compare `updated`; return 409 if changed since fetch
- [ ] Migration 0021: `ticket_revisions` table (bumped from 0020 — Initiative A claimed 0017–0019)
  - `id` uuid PK
  - `ticket_id` uuid FK
  - `suggested_revision` jsonb (what Scope Cop proposed)
  - `applied_revision` jsonb (what actually got pushed — may differ from suggestion if user edited)
  - `original_jira_state` jsonb (snapshot before push, for rollback)
  - `applied_at` timestamp
  - `applied_by` uuid (clerk user)
- [ ] `src/models/ticket_revision.py` ORM model
- [ ] Tests: 409 on stale, audit row written on success

### B4 — Backend endpoints
- [ ] GET `/api/scope-cop/tickets/{key}/revision-preview` — returns `{original, suggested_revision, fetched_updated_at}`; uses cached `ticket_analyses.suggested_revision` or triggers a fresh Scope Cop run if absent
- [ ] PATCH `/api/scope-cop/tickets/{key}` — body `{revision, fetched_updated_at}`; pushes to Jira, writes `ticket_revisions` row, re-runs Scope Cop scoring on the updated content
- [ ] Lead role required on both
- [ ] Tests: dirty check, conflict, audit row written, scoring re-runs

### B5 — Editor pane component (used inside B8 modal, not a standalone drawer)
- [ ] New component `TicketEditorPane` — center pane of the Plan Review Modal
- [ ] Side-by-side layout: original Jira content (read-only, left) vs suggested revision (editable, right)
- [ ] Diff highlight on changed fields (use `diff` npm package or simple per-field comparison)
- [ ] Per-field "Reset to suggestion" button (lets user undo their edits)
- [ ] Track `currentState` vs `originalState` per ticket — drives the modal's [Review and Commit] button state (enabled if *any* ticket in the plan has `current !== original`, since that's the only condition that produces a Jira write)
- [ ] Toast on push success, 409 banner with "Reload from Jira" on conflict (raised by B10's batched push)
- [ ] Tests (vitest): dirty logic per ticket, conflict handling

### B6 — Surface points in existing UI
- [ ] Scope Cop results table (wherever it lives in `apps/web/src/pages/`): each non-ready row gets a "Refine" button → opens drawer for that ticket
- [ ] Sprint Planner: warnings from Scope Cop enrichment include the same "Refine" affordance inline
- [ ] After successful push: re-fetch the analysis cache so the row's score updates in place

### B7 — Telemetry on adoption + AI quality
- [ ] Track per-team: `revisions_proposed`, `revisions_accepted_verbatim`, `revisions_edited_before_push`, `revisions_dismissed`
- [ ] Per-field edit-rate: if leads consistently rewrite the `description` field heavily before pushing, prompt is failing on description — surface for tuning
- [ ] Exec Dashboard: "Scope Cop revision acceptance rate" trailing 8 sprints
- [ ] Alert: if acceptance rate < 30% for a team, surface "Scope Cop suggestions aren't landing — review the prompt"

### B8 — Plan Review Modal: triage view
- [ ] New top-level component `PlanReviewModal` — full-screen takeover, opens automatically after Sprint Brain plan generation (and B0's Scope Cop run) completes
- [ ] Three-pane layout:
  - **Left rail**: scrollable list of all assigned tickets. Each row: status pill (`ready` / `needs_work` / `blocked` from cached `ticket_analyses`), assignee avatar, ticket title, story points. Click to select.
  - **Center**: `TicketEditorPane` (B5) for the selected ticket
  - **Right rail**: assignee context — display name, current sprint load (assigned points / safe capacity), relevant velocity citation from Sprint Brain's `reasoning` field, link to "reassign" (opens minimal picker)
- [ ] Bottom-right: **[ Review and Commit ]** button (replaces any "Push to Jira" naming elsewhere). Always enabled (no dirty gate) — clicking proceeds to B9 carousel regardless of edits
- [ ] Top-right: secondary [ Save Draft ] button — persists current edits without committing; user can come back later
- [ ] Keyboard: `j`/`k` or `↑`/`↓` to move between tickets in the left rail; `Cmd+Enter` to open carousel
- [ ] Tests (vitest): rail renders with correct status pills, selection routing, "Review and Commit" navigation

### B9 — Sign-off Carousel (mandatory, with approval memory + bulk-approve)
- [ ] New component `SignOffCarousel` — full-screen, triggered exclusively from B8's [Review and Commit] button. No skip-review escape hatch.
- [ ] One-ticket-per-screen layout:
  - Header: progress indicator (`Ticket 4 of 12`) + ticket key + assignee chip
  - Body: original Jira content + revised content (if edited in B8) + Sprint Brain reasoning citation
  - Footer actions: **[Approve]** (next), **[Go back to edit]** (returns to B8 with this ticket selected), **[Approve next 5]** (only shown when ≥5 unapproved tickets remain; bulk action still records individual `approved_at` per ticket for audit)
- [ ] **Session-scoped approval memory**: per-ticket approval state (`{ticket_id: approved_at}`) lives in the modal's React state for the planning session. Going back to edit ticket #4 does *not* reset approvals on #1–#3. Editing a ticket *does* clear its own prior approval — re-approve required if content changed.
- [ ] Final screen after all tickets approved: commit summary card showing `N tickets to push`, `M ticket-revision audit rows to write`, single **[Push to Jira]** button triggers B10
- [ ] Backing out (Esc or "Back to Triage") preserves approvals so the lead can fix one issue and resume
- [ ] Tests (vitest): approval memory across navigation, edit-invalidates-own-approval, bulk-approve records N audit timestamps, final screen gating

### B10 — Batched commit to Jira
- [ ] New endpoint `POST /api/sprint-brain/plans/{plan_id}/commit` — body `{ approvals: [{ticket_key, revision?, approved_at, fetched_updated_at}] }`
- [ ] For each ticket: if `revision` present, call Jira `PUT /rest/api/3/issue/{key}` with the revised fields; for all tickets, set Jira sprint custom field + assignee from the plan
- [ ] Write `ticket_revisions` row per ticket — `approved_at`, `approved_by`, `applied_revision` (null if no revision), `original_jira_state` snapshot
- [ ] Atomic-ish semantics: collect per-ticket success/failure; if any single push 409s, return `{committed: [...], conflicts: [...]}` so the carousel can surface "3 tickets pushed, 1 conflict — review and retry"
- [ ] Lead role required
- [ ] Tests: happy path (all push), partial conflict (some 409), audit rows written

## Open questions

1. **Editor reachable on ready tickets too?** All tickets in the plan land in B8's left rail regardless of score. Editing a `ready` ticket is allowed but soft-discouraged via styling (muted "this ticket is already ready" hint above the editor). No hard gate.
2. **ADF vs plain text.** v1 is plain text in/out. Lossy for users who format with checklists, code blocks, mentions. Decide whether to invest in ADF round-tripping now or after measuring whether anyone complains.
3. **Bulk-approve threshold.** B9's [Approve next 5] uses a hardcoded 5. Should the threshold be team-configurable (some leads might want 10), or tied to a runtime heuristic (e.g. only show when next N tickets are all `ready`)? Default: hardcoded 5 for v1; revisit after a quarter of usage.
4. **Story-point change side-effects.** If the lead bumps points from 3 to 5 in the editor, that changes Sprint Brain's capacity math for any sprint this ticket lands in. Auto-trigger a re-plan, or just persist quietly and let the next planning run pick it up? Default: persist quietly; surface a banner in the modal "ticket points changed — re-plan capacity?" before [Review and Commit].
5. **Assignee / mentions.** If Scope Cop suggests "assign to backend-team," do we round-trip Jira mention syntax? Out of scope for v1; description-only.
6. **30-ticket-sprint UX.** A team with very large sprints clicks Approve 30 times. Bulk-approve mitigates but doesn't eliminate. Monitor B7 telemetry on session-completion time; if it exceeds ~3 minutes for the median lead, revisit the carousel cadence or introduce smarter bulk grouping (e.g. "approve all `ready` tickets at once").
7. **Save Draft semantics.** B8's [Save Draft] persists edits without committing. Does a draft expire? Does generating a new plan invalidate the draft? Default: drafts tied to a `plan_id` UUID; new plan generation = new id = old draft is orphaned but kept for 30 days for recovery.

## Verification gates

Before merging B8 (the first user-facing surface):
- [ ] B0 verified: planning a sprint produces `ticket_analyses` rows for every assigned ticket
- [ ] B5 + B8 together: open the Plan Review Modal on a real generated plan, navigate the left rail, edit a ticket, confirm dirty state surfaces in the editor pane
- [ ] B9 carousel: approve all tickets, confirm progress indicator advances, confirm `[Approve next 5]` records 5 distinct `approved_at` timestamps
- [ ] B9 approval memory: approve 3, go back to edit ticket #4, return to carousel — confirm #1–#3 still approved
- [ ] B10 batched push: commit a plan with mixed edited/unedited tickets — confirm Jira reflects edits, sprint assignment lands for all, audit rows written
- [ ] B10 conflict: edit a ticket in Jira UI mid-flow, attempt push — confirm 409 surfaces per-ticket and the carousel allows resuming after fix
- [ ] Audit row spot-check — `original_jira_state` snapshot is complete enough to support a future rollback feature
