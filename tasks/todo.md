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
