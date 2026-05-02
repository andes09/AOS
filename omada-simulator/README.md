# omada-simulator

Foundational, environment-aware configuration for the Omada simulator.

## What this is

This package is the **config infrastructure** that the Omada simulator's
behavioral logic will build on top of. It provides:

- A `--env` flag that selects a YAML config from `config/environments/`
- Pydantic-validated environment models (Omada URL, Jira coordinates, safety rules)
- Connectivity checks against the Omada API
- A deliberate refusal mechanism for production
- A team config under `config/teams/`

The simulator's behavior — Jira driver, the developer loop, the orchestrator,
audit logging — is **not in this package**. Those land in a follow-up task.

## Setup

Requires Python 3.11+.

```bash
cd omada-simulator
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with your real Jira email + API token + Omada Clerk session token.
```

## How environments work

Each environment is one YAML file under `config/environments/`. The `--env`
flag picks one:

```
config/environments/
├── local.yaml          → http://localhost:8000
├── sims.yaml           → https://api-sims-cc98.up.railway.app
└── prod_blocked.yaml   → refuses to run
```

Every environment declares **safety rules** in its YAML:

| Field                      | Purpose                                                |
| -------------------------- | ------------------------------------------------------ |
| `allow_production`         | Hard gate on URLs containing `production`              |
| `required_url_substrings`  | The Omada URL **must** contain at least one of these   |
| `block_url_substrings`     | The Omada URL **must not** contain any of these        |
| `max_real_users_in_org`    | If Omada returns more orgs than this, refuse to run    |
| `require_simulated_org`    | If true, the active org must have `is_simulated=True`  |
| `refuse_with_message`      | If set, refuse immediately with this message           |

These rules are enforced at every `--check-env` invocation, before any HTTP
call that could mutate state.

## Adding a new environment

```bash
cp config/environments/local.yaml config/environments/staging.yaml
# Edit URLs, jira coordinates, and safety substrings to match staging.
python -m src.main --check-env --env staging
```

The validator will tell you if the URL fails the substring rules or if Omada
returns more orgs than `max_real_users_in_org`.

## Where secrets go

Strict boundary:

- **`.env`** (gitignored) — `JIRA_EMAIL`, `JIRA_API_TOKEN`, `OMADA_CLERK_TOKEN`
- **YAML files** (committed) — every other piece of config

If a value would cause a security incident if it leaked, it goes in `.env`.
If it's safe to commit, it goes in YAML. There is no third bucket.

`.env.example` is committed as a template; `.env` itself is `.gitignore`d.

## Running --check-env

```bash
python -m src.main --check-env --env local
```

What it does, in order:

1. Loads `config/environments/{env}.yaml` and validates it with pydantic.
2. Runs `validate_safety` — refuse if `refuse_with_message` is set, then
   enforce required/blocked URL substrings and the `allow_production` gate.
3. Loads secrets from `.env`.
4. Prints a banner showing the active config.
5. `GET {api_url}/health` to confirm Omada is reachable.
6. `GET {api_url}/api/organizations` with the Clerk token, then verifies
   the org count is at or below `max_real_users_in_org` and (if required)
   that an `is_simulated=True` org exists.
7. Prints `✓ All checks passed`.

### Expected output

For `--env local` (when local Omada is running):

```
============================================================
Active environment: local
  Omada API: http://localhost:8000
  Jira:      https://omada-sim.atlassian.net
  Safety:    allow_production=false, max_users=5
============================================================
✓ All checks passed
```

For `--env prod_blocked`:

```
Refusing to run simulator against production.
Use --env local for local development or --env sims for the
Railway Sims environment.
```

(No HTTP calls are attempted.)

### Common failure modes

| Symptom                                          | Likely cause                                          |
| ------------------------------------------------ | ----------------------------------------------------- |
| `Cannot reach Omada at .../health`               | Local Omada API isn't running                         |
| `Omada rejected OMADA_CLERK_TOKEN (401)`         | Clerk session expired — copy a fresh `__session` cookie |
| `Missing required secret(s): ...`                | `.env` not created or missing a key                   |
| `Safety violation: ... contains 'production'`    | URL has `production` and `allow_production=false`     |
| `Environment config not found: .../locall.yaml`  | Typo in `--env` argument                              |

## Production blocked

`prod_blocked.yaml` exists as a **deliberate refusal mechanism**, not a
configuration option. Anyone running `--env prod_blocked` gets a clear
message and zero HTTP calls.

This is intentional: keeping a refusal config alongside the working configs
means there's no path where pointing at production is plausible. To run
against the real production environment, you'd need to author a new YAML
that explicitly sets `allow_production: true` — a deliberate, reviewable act.

## Tests

```bash
pytest tests/ -v --cov=src.config
```

26 tests covering YAML loading, safety validation, secret loading, the
banner, and async connectivity (success, unreachable, 401, 500,
too-many-orgs, simulated-org enforcement). Coverage of `src/config.py` is
96%.
