# omada-simulator

Stage 1: drives a fake engineering team through 3 sprints in a real
Jira Cloud sandbox while Omada observes through its normal sync flow.
The goal is to surface integration bugs and produce a written report.

## What's in this package

- `--check-env` — load env YAML, validate safety, probe Omada `/health` + `/api/me`
- `--setup` — create Jira `SIM` project, generate a 100-ticket pool, add Blocks links
- `--simulate` — run 3 sprints concurrently with 4 simulated developers
- `--reset` — delete the Jira SIM project and remove local state
- `--dry-run` — preview any of `--setup`/`--simulate`/`--reset` without API calls

All Jira and Omada calls are audited to `output/jira_audit.log` and
`output/omada_audit.log`. The Omada observer never raises — every
non-2xx, timeout, or decode error is logged and returned as `None`, so
broken endpoints surface in the final bug report rather than crashing
the simulator.

## Prerequisites

- Python 3.11+
- A running Omada API (locally via `uvicorn src.main:app --reload` from
  `apps/api/`, or a Railway deployment such as the Sims env)
- A Clerk session token for the Omada user you've signed in as
- (Optional) An Atlassian API token and email for the Jira account that
  will receive simulator-generated tickets

## Setup

```bash
cd omada-simulator
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with real values (see below).
```

### Omada Clerk token

The simulator needs a Clerk session JWT to call Omada. These tokens
expire ~60 s after they're issued, and we can't sign in programmatically
when the account uses Google OAuth. So the workflow is:

1. Open the Omada web app (e.g. http://localhost:5173) and sign in.
2. In the browser console, run:
   ```js
   await window.Clerk.session.getToken()
   ```
3. Pass the resulting JWT to the simulator via `--token`:
   ```bash
   python -m src.main --simulate --env local --token "eyJ..."
   ```

`OMADA_CLERK_TOKEN` in `.env` is still honoured as a fallback (handy for
one-shot calls that complete in under a minute), but `--token` is the
practical path. If a request 401s mid-run, the observer prints a
reminder to grab a fresh token and re-run.

## How environments work

Each environment is one YAML file under `config/environments/`. The
`--env` flag picks one:

```
config/environments/
├── local.yaml          → http://localhost:8000
├── sims.yaml           → https://api-sims-cc98.up.railway.app
└── prod_blocked.yaml   → refuses to run (no HTTP calls made)
```

Every environment declares **safety rules** in its YAML:

| Field                      | Purpose                                              |
| -------------------------- | ---------------------------------------------------- |
| `allow_production`         | Hard gate on URLs containing `production`            |
| `required_url_substrings`  | The Omada URL **must** contain at least one of these |
| `block_url_substrings`     | The Omada URL **must not** contain any of these      |
| `refuse_with_message`      | If set, refuse immediately with this message         |

These rules are enforced at every `--check-env` invocation, before any
HTTP call is made.

## Adding a new environment

```bash
cp config/environments/local.yaml config/environments/staging.yaml
# Edit URLs, jira coordinates, and safety substrings to match staging.
python -m src.main --check-env --env staging
```

The validator will tell you if the URL fails the substring rules.

## Where secrets go

Strict boundary:

- **`.env`** (gitignored) — `JIRA_EMAIL`, `JIRA_API_TOKEN`, optional
  `OMADA_CLERK_TOKEN` (prefer `--token` at the CLI)
- **YAML files** (committed) — every other piece of config

If a value would cause a security incident if it leaked, it goes in
`.env`. If it's safe to commit, it goes in YAML. There is no third bucket.

`.env.example` is committed as a template; `.env` is `.gitignore`d.

## Running --check-env

```bash
python -m src.main --check-env --env local
python -m src.main --check-env --env sims
python -m src.main --check-env --env prod_blocked
```

What it does, in order:

1. `load_environment(args.env)` — load and pydantic-validate the YAML.
2. `load_secrets()` — load `.env`; lists every missing secret in one shot.
3. `validate_safety(env)` — refuse if `refuse_with_message` is set; then
   enforce `required_url_substrings`, `block_url_substrings`, and the
   `allow_production` gate.
4. `print_environment_banner(env, secrets)` — show what's about to run.
5. `resolve_clerk_token(args.token, secrets)` — picks the token: `--token`
   wins over `OMADA_CLERK_TOKEN` from `.env`; errors with guidance if
   neither is set.
6. `verify_connectivity(env, clerk_token)`:
   - `GET {api_url}/health` — confirms Omada is reachable.
   - `GET {api_url}/api/me` with the supplied Clerk JWT — confirms
     the signed-in account is recognised by Omada.
7. Prints `✓ All checks passed`.

### Expected output for `--env local` (Omada running locally)

```
============================================================
Active environment: local
  Omada API: http://localhost:8000
  Jira:      https://omada-sim.atlassian.net
  Safety:    allow_production=false
============================================================
✓ All checks passed
```

### Expected output for `--env prod_blocked`

```
Refusing to run simulator against production.
Use --env local or --env sims.
```

No HTTP calls are attempted — the refusal happens during
`validate_safety`, before `verify_connectivity` is reached.

### Expected output for `--env <typo>`

```
FileNotFoundError: Environment config not found:
.../config/environments/<typo>.yaml.
Available environments: ['local', 'prod_blocked', 'sims']
```

## Troubleshooting

| Symptom                                          | Likely cause                                            |
| ------------------------------------------------ | ------------------------------------------------------- |
| `Omada not running at http://localhost:8000`     | Local Omada API isn't running — start it from `apps/api/` |
| `Clerk token expired. Re-grab from DevTools...`  | Session expired — copy a fresh `__session` cookie       |
| `Missing required secret(s): ...`                | `.env` not created or missing a key                     |
| `Safety violation: ... contains 'production'`    | URL has `production` and `allow_production=false`       |
| `Environment config not found: .../locall.yaml`  | Typo in `--env` argument                                |
| Wrong Jira URL in banner                         | Edit `jira.url` in `config/environments/{env}.yaml`     |

## Why prod_blocked.yaml exists

`prod_blocked.yaml` is a **deliberate refusal mechanism**, not a
configuration option. Anyone running `--env prod_blocked` gets a clear
message and zero HTTP calls.

This is intentional: keeping a refusal config alongside the working
configs means there's no path where pointing at production is plausible.
To run against the real production environment, you'd need to author a
new YAML that explicitly sets `allow_production: true` — a deliberate,
reviewable act.

## Running the Stage 1 simulator

Once `--check-env --env local` passes, the simulator runs in three
phases. The first two are gated so you can't run them out of order, and
both support `--dry-run` so you can preview what would happen without
calling Jira or Omada.

### 1. Setup — create the Jira project and ticket pool

```bash
python -m src.main --setup --env local --dry-run    # preview only
python -m src.main --setup --env local              # actually create SIM project
python -m src.main --setup --env local --force      # overwrite existing state
```

This creates a Jira Scrum project keyed `SIM`, generates 100 tickets
according to `config/teams/stage1_team.yaml`'s distribution, and adds
~10% "Blocks" issue links between random pairs. The created ticket keys
and pool state are persisted to `output/setup_state.json`. The simulator
refuses to overwrite an existing state file without `--force`.

### 2. Simulate — run 3 sprints

```bash
python -m src.main --simulate --env local --dry-run    # show plan only
python -m src.main --simulate --env local              # run for real
```

For each sprint the simulator:
1. Picks 5–8 tickets per developer from the unused pool.
2. Creates a Jira sprint, adds the picked issues, activates it.
3. Triggers an Omada sync (`POST /api/integrations/jira/sync`).
4. Generates a Sprint Brain plan (`POST /api/sprint-brain/plan`).
5. Pushes the plan to Jira (`POST /api/sprint-brain/push-to-jira`).
6. Runs 4 developer coroutines concurrently via `asyncio.gather`, each
   transitioning their assigned tickets to "In Progress" then "Done"
   based on per-dev completion rate and speed.
7. Closes the sprint, triggers another sync, fetches retro, velocity
   health, and dependency-radar snapshots into `output/sprint_{N}_*.json`.

After all sprints land, the simulator writes
`output/simulation_results.json` and `output/BUGS_INTEGRATION.md` — a
human-readable report categorising bugs as Critical / High / Medium with
pointers to the raw response files for follow-up.

### 3. Reset — tear down

```bash
python -m src.main --reset --env local --confirm
python -m src.main --reset --env local --dry-run --confirm   # preview
```

Deletes the Jira `SIM` project and removes `output/setup_state.json`.
The simulator refuses to delete any Jira project whose key does not
start with `SIM`.

## Safety rails

1. The Jira project key must start with `SIM`. Anything else and
   `--setup` / `--reset` refuse.
2. `--reset` requires `--confirm` — there is no implicit deletion.
3. `--setup` requires `--force` to overwrite an existing state file.
4. Every environment's `safety.required_url_substrings` /
   `block_url_substrings` are enforced before any HTTP call.
5. Jira calls are rate-limited to ≤10 req/sec with exponential backoff
   on 429 and 5xx.

## Output files

```
output/
├── setup_state.json            ← Jira project + ticket pool snapshot
├── simulation_results.json     ← per-sprint committed/completed/spillover
├── BUGS_INTEGRATION.md         ← the human-readable bug report
├── sprint_{N}_plan.json        ← Sprint Brain plan response
├── sprint_{N}_push.json        ← push-to-jira response
├── sprint_{N}_retro.json       ← retro response
├── sprint_{N}_health.json      ← velocity / health response
├── sprint_{N}_deps.json        ← dependency-radar response
├── jira_audit.log              ← every Jira call: method | path | status | ms
└── omada_audit.log             ← every Omada call: method | path | status | preview
```

## Tests

```bash
pytest tests/ -v --cov=src.config
```

Coverage of `src/config.py` is ≥90%. Connectivity tests use
`httpx.MockTransport` and never touch the network.
