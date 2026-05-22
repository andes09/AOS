# Stage 2 — How to Run

The stage-2 matrix runs the same sprints across multiple **team archetypes** and **assignment strategies**, then aggregates results so you can compare them.

| Strategy    | What it does                                                  |
|-------------|---------------------------------------------------------------|
| `random`    | Uniform random dev per ticket. Baseline / strawman.           |
| `omada`     | Calls SprintBrain's `/api/sprint-brain/plan` and applies it.  |
| `algorithm` | Load-balanced by story points (placeholder for future algos). |

| Archetype       | What varies from balanced                                            |
|-----------------|----------------------------------------------------------------------|
| `balanced`      | Reference — 4 devs, normal speed and completion.                     |
| `small`         | 2 devs (Casey, Drew), pool 60.                                       |
| `large`         | 8 devs, pool 200.                                                    |
| `struggling`    | Low completion_rate (0.45-0.60), slower speed, dense dependencies.   |
| `meeting_heavy` | Normal completion quality but ~45% throughput loss to meetings.      |

Full matrix per run: **5 archetypes × 3 strategies = 15 teams**, each with its own Jira project and Omada team.

---

## 1. Prerequisites

### One-time setup

1. **Local apps/api running** (the Omada backend the simulator calls):
   ```bash
   cd apps/api
   uvicorn src.main:app --reload
   ```
   Confirm health: `curl http://localhost:8000/health` → 200.

2. **Celery worker + Redis** (so SprintBrain's `/plan` can return real plans):
   ```bash
   cd apps/api
   # Redis: docker run --rm -p 6379:6379 redis  (or however you run it locally)
   celery -A src.celery_app worker --loglevel=info
   ```

3. **Jira creds in `omada-simulator/.env`** (copy from `.env.example`):
   ```
   JIRA_EMAIL=you@example.com
   JIRA_API_TOKEN=<your Atlassian API token>
   ```

4. **Feature flag for per-team Omada creation** (M5). Already set for local:
   ```yaml
   # apps/api/config/features/local.yaml
   allow_team_creation_via_api: true
   ```

### Verify connectivity before running

```bash
cd omada-simulator
python -m src.main --env local --check-env
```

Expected: `✓ All checks passed`. If you get a 401 on `/api/me`, the apps/api isn't running with `clerk_auth: false` (check `apps/api/config/features/local.yaml`).

---

## 2. Smoke test (run this first)

The fastest way to validate the whole pipeline. 1 archetype × 3 strategies × 1 sprint × 1 run — finishes in ~3 minutes.

```bash
cd omada-simulator
python -m src.main --env local --stage 2 --smoke-test
```

What happens:
1. Creates 3 Jira projects: `SIM_BAL_RAND`, `SIM_BAL_OMAD`, `SIM_BAL_ALGO` (~10s each).
2. For each project, calls `POST /api/teams` to create a dedicated Omada team with the 4 balanced devs. If `allow_team_creation_via_api` is disabled, falls back silently to the org's primary team (a single shared team across all 3 — `summary.md` will note this).
3. Generates 100 tickets per project using the same `run_seed` for all 3 — identical pools, only assignment differs.
4. For each project, runs 1 one-minute sprint:
   - Random: round-robins tickets onto devs.
   - Omada: calls SprintBrain's `/plan`, maps UUIDs to dev names, applies the assignment.
   - Algorithm: load-balances by story points.
5. Writes results to `output/run_001/balanced_<strategy>/simulation_results.json` for each.

### What success looks like

```
=== Stage 2 smoke test ===
1 archetype (balanced) x 3 strategies x 1 sprint x 1 run

=== Run 1/1: 3 teams (1 archetypes × 3 strategies) ===
[setup]   SIM_BAL_RAND: created Omada team abc123...
[setup]   SIM_BAL_RAND: 100 tickets created (board_id=42)
[setup]   SIM_BAL_OMAD: created Omada team def456...
... (etc)

[simulate] balanced × random
=== Sprint 1/1 ===
Picked 26 tickets for this sprint
Running 4 developers for 1 minutes...
[Sprint 1/1] ████████████████ 100% | 01:00 elapsed | 18/26 tickets done | 0 in progress
Sprint 1 done: 18/26 completed (plan=fail push=fail retro=ok)

[simulate] balanced × omada
... (plan=ok push=ok)

[simulate] balanced × algorithm
... 

✓ Smoke test complete
  Inspect: .../output/run_001/balanced_*/simulation_results.json
```

The signal you want to see:
- All 3 strategies produced sprint results (none crashed mid-sprint).
- `omada` strategy logged `plan=ok push=ok` (SprintBrain returned a real plan and the simulator applied it).
- `output/run_001/balanced_omada/sprint_1_plan.json` is non-empty and contains an `"assignments": [...]` array.

### If something failed

| Symptom | Likely cause | Fix |
|---|---|---|
| `Omada not running at http://localhost:8000` | apps/api isn't up | start uvicorn |
| `/api/me returned 401` | `clerk_auth` is on | set `clerk_auth: false` in `local.yaml` |
| All 3 strategies `completed: 0` | Jira transitions failed | check `output/run_001/balanced_*/jira_audit.log` |
| `omada` strategy `plan=fail` | SprintBrain didn't return | check Celery worker logs |
| `Omada team creation unavailable — sharing org primary team` | M5 feature flag off | check `allow_team_creation_via_api: true` in `apps/api/config/features/local.yaml` |
| Jira `400` on project create with key already exists | Previous run left projects around | see Cleanup section below |

---

## 3. Aggregate the results

After any run, produce the comparison table:

```bash
python -m src.main --env local --stage 2 --aggregate
```

Writes:
- `output/aggregate/summary.csv` — one row per `(archetype, strategy)` cell with mean/std completion rate, spillover, integration-health percentages.
- `output/aggregate/summary.md` — headline table, per-archetype 3-row sub-tables, integration-health rollup, and a "notes" section flagging any failed setups or shared-Omada-team caveats.

After the smoke test you'll see 3 rows (all `balanced`). After a full matrix you'll see 15.

### Reading the summary

The interesting question is the **per-archetype completion-rate delta between strategies**:
- `balanced × omada` ≈ `balanced × random` → plausible noise floor on a healthy team.
- `struggling × omada` materially > `struggling × random` → SprintBrain is earning its keep.
- `meeting_heavy × omada` > others → smart assignment compensates for throughput loss.

If deltas are flat across the board with `--runs 1`, the noise floor is drowning the signal — bump runs (see §5).

---

## 4. Full matrix run (15 teams, 1 run)

Once smoke is green, run the full 5-archetype matrix:

```bash
python -m src.main --env local --stage 2 --simulate --runs 1
python -m src.main --env local --stage 2 --aggregate
```

**Wall clock: ~45 min sequential** (15 teams × 3 sprints × 1 min). For faster iteration during development, narrow to one archetype or strategy:

```bash
# Only struggling teams
python -m src.main --env local --stage 2 --simulate --runs 1 --archetype struggling

# Only the omada strategy across all archetypes (debugging SprintBrain)
python -m src.main --env local --stage 2 --simulate --runs 1 --strategy omada
```

---

## 5. Multi-run for statistical confidence

To tell signal from noise, you need multiple runs:

```bash
# 5 runs = ~3.75 hours sequential. Good for a lunch break.
python -m src.main --env local --stage 2 --simulate --runs 5

# 50 runs = ~37.5 hours sequential. Overnight + a workday.
python -m src.main --env local --stage 2 --simulate --runs 50

# Aggregate any time after — the aggregator reads everything under output/run_*/
python -m src.main --env local --stage 2 --aggregate
```

Each run writes to `output/run_NNN/` so you can interrupt mid-way and aggregate what completed. The seed derivation (`stable_seed(archetype, run_idx)`) guarantees:
- For one `(archetype, run_idx)`, the 3 strategies face an identical ticket pool — the only confound is the assigner.
- For different runs, the pools vary, so 50 runs gives statistical power.

### Speeding up: parallel-by-archetype (M6)

Enable in `config/stage2.yaml`:
```yaml
parallel_teams: true
```

This runs the 5 archetype groups concurrently (strategies within an archetype stay sequential since they share board state). Wall clock for 50 runs drops from ~37.5h to ~7.5h.

Setup phase stays sequential regardless — Jira's 10 req/sec org-wide rate limit will otherwise throttle concurrent project creation.

---

## 6. Output layout

```
omada-simulator/output/
├── run_001/
│   ├── balanced_random/
│   │   ├── setup_state.json           (project_key, board_id, ticket pool, run_seed)
│   │   ├── simulation_results.json    (per-sprint outcomes)
│   │   ├── sprint_1_plan.json         (Omada strategy: the SprintBrain plan; others: {})
│   │   ├── sprint_1_push.json         (push-to-jira response)
│   │   ├── sprint_1_retro.json
│   │   ├── sprint_1_health.json
│   │   ├── sprint_1_deps.json
│   │   ├── sprint_1_features.json
│   │   ├── sprint_2_*.json ...
│   │   ├── sprint_3_*.json ...
│   │   ├── jira_audit.log             (M6: per-team)
│   │   └── omada_audit.log            (M6: per-team)
│   ├── balanced_omada/
│   ├── balanced_algorithm/
│   ├── small_random/
│   ├── ... (15 dirs after a full matrix run)
│   └── matrix_meta.json               (run_idx, started_at, completed_at, team list)
├── run_002/
└── aggregate/
    ├── summary.csv
    └── summary.md
```

`simulation_results.json` shape per team:
```json
{
  "env": "local",
  "team": "balanced × omada",
  "archetype": "balanced",
  "strategy": "omada",
  "project_key": "SIM_BAL_OMAD",
  "sprint_length_minutes": 1,
  "total_sprints": 3,
  "omada_team_id": "uuid-or-null",
  "run_seed": 1234567,
  "sprints": [
    {
      "sprint_num": 1, "jira_sprint_id": 162,
      "committed": 26, "completed": 18, "spillover": 8,
      "sync_ok": true, "plan_ok": true, "push_ok": true,
      "retro_ok": true, "health_ok": true, "deps_ok": true, "features_ok": true,
      "ticket_results": { "SIM_BAL_OMAD-1": "completed", ... }
    }, ...
  ],
  "completed_at": "..."
}
```

---

## 7. Cleanup between runs

Stage 2 doesn't yet have a one-shot matrix reset. For now use stage-1's per-project reset:

```bash
# Delete one matrix project (repeat for each)
python -m src.main --env local --reset --confirm --project-key SIM_BAL_RAND

# Or wipe the output dir to re-aggregate freshly:
rm -rf omada-simulator/output/run_*
rm -rf omada-simulator/output/aggregate
```

Jira reserves deleted project keys for ~30 days (post-deletion reservation window). If you re-run after deleting, projects come back at their existing keys. If you hit a 400 on `--simulate`'s project create, give it time or use different project codes (edit `config/stage2.yaml`'s `archetype_codes` / `strategy_codes`).

The matrix is **idempotent**: re-running `--simulate` with the same matrix config will reuse existing projects (via `get_or_create_project`). Tickets get appended to the pool, not deduplicated — `--reset-sprints` per project is the cleanest way to reset between runs.

---

## 8. Tweaking sprint length

The default `sprint_length_minutes: 1` in `config/stage2.yaml` is fine for smoke testing. For realistic data you probably want longer:

```yaml
# config/stage2.yaml
defaults:
  sprint_length_minutes: 5    # ← bump this
  total_sprints: 3
```

5 min sprints × 3 sprints × 15 teams = 225 min = ~4 hours per run. Multiply by `--runs N` for the total.

You can also tweak per-archetype by editing `config/archetypes/<name>.yaml`'s `sprint_length_minutes` — the matrix uses the archetype's value, falling back to defaults if missing.

---

## 9. Adding a new archetype

1. Create `config/archetypes/your_archetype.yaml` (copy `balanced.yaml` as template).
2. Tune `developers[].completion_rate` and `speed` per the persona.
3. Add to `config/stage2.yaml`:
   ```yaml
   archetypes:
     - {name: "your_archetype"}
   project_key:
     archetype_codes:
       your_archetype: YOU   # 3-letter code for project key suffix
   ```
4. The matrix picks it up automatically. Verify:
   ```bash
   python -m src.main --env local --stage 2 --simulate --dry-run --runs 1 --archetype your_archetype
   ```

---

## 10. Adding a new strategy

1. Create `src/assigners/your_strategy_assigner.py` subclassing `BaseAssigner`:
   ```python
   from src.assigners.base import BaseAssigner, AssignmentResult, SprintContext, empty_by_dev, TicketAssignment

   class YourStrategyAssigner(BaseAssigner):
       name = "your_strategy"

       def assign(self, ctx: SprintContext) -> AssignmentResult:
           by_dev = empty_by_dev(ctx.developers)
           assignments = []
           # ... your logic. Must cover every ticket in ctx.picked_tickets.
           return AssignmentResult(by_dev=by_dev, assignments=assignments)
   ```
2. Register in `src/assigners/__init__.py`:
   ```python
   from src.assigners.your_strategy_assigner import YourStrategyAssigner
   _REGISTRY["your_strategy"] = YourStrategyAssigner
   ```
3. Add to `config/stage2.yaml`:
   ```yaml
   strategies: ["random", "omada", "algorithm", "your_strategy"]
   project_key:
     strategy_codes:
       your_strategy: YOUR
   ```
4. Add tests to `tests/test_assigners.py` covering the coverage invariant (every ticket assigned exactly once).

---

## 11. Troubleshooting

| Issue | Where to look |
|---|---|
| Tests don't pass | `pytest tests/ -q` from omada-simulator/ — should be 89 passing |
| Jira API errors mid-run | `output/run_NNN/<team>/jira_audit.log` |
| Omada API errors mid-run | `output/run_NNN/<team>/omada_audit.log` |
| SprintBrain returns empty plan | Celery worker logs; verify `/api/sprint-brain/plan` works via curl with a populated sprint |
| Aggregator says "No runs" | Check `output/run_*/` actually exists and contains `<team>/simulation_results.json` |
| Want to debug one team | `--archetype <name> --strategy <name>` filters the matrix to a single cell |
| Need a real plan for debugging | Inspect `output/run_NNN/<team>/sprint_N_plan.json` — that's the raw SprintBrain response |

---

## 12. Architecture quick reference

- **Plan file**: `~/.claude/plans/lets-work-on-stage-quizzical-metcalfe.md` (full design with all milestones and design rationale)
- **Project todo**: `tasks/todo.md`
- **Entry point**: `src/main.py` → `_run_stage2` → `src/matrix.run_matrix`
- **Per-team simulation**: `src/simulation.run_team_simulation`
- **Assigner contract**: `src/assigners/base.py` (`BaseAssigner`, `SprintContext`, `AssignmentResult`)
- **Matrix shape**: `src/matrix.expand_matrix` → list of `TeamRun` dataclasses
- **Aggregator**: `src/aggregator.aggregate` → CSV + MD
- **Same-pool fairness**: `src/team_factory.stable_seed(archetype, run_idx)` is shared across the 3 strategies of one archetype/run

Total test coverage: `pytest tests/ -q` → **89 passing** (assigners, stage2_config, matrix, aggregator, plus the original config + omada_observer tests).
