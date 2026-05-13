# omada-simulator

Foundational, environment-aware configuration for the Omada simulator.

## What this is

This package is the **config infrastructure** the Omada simulator's
behavioral logic will build on top of. It provides:

- A `--env` flag that selects a YAML config from `config/environments/`
- Pydantic-validated environment models (Omada URL, Jira coordinates, safety rules)
- Connectivity checks against the Omada API (`/health` + `/api/me`)
- A deliberate refusal mechanism for production
- A team config under `config/teams/`

The simulator's behavior — Jira driver, the developer loop, the
orchestrator, audit logging — is **not in this package**. Those land in
a follow-up task.

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

### Getting the Omada Clerk session token

1. Open Omada locally and sign in.
2. Open DevTools → Application → Cookies → your Omada origin.
3. Copy the value of the cookie named `__session`.
4. Paste it into `.env` as `OMADA_CLERK_TOKEN=...`.

Clerk session tokens expire (typically within an hour). When you see
`Clerk token expired` from `--check-env`, repeat the steps above.

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

- **`.env`** (gitignored) — `JIRA_EMAIL`, `JIRA_API_TOKEN`, `OMADA_CLERK_TOKEN`
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
5. `verify_connectivity(env, secrets)`:
   - `GET {api_url}/health` — confirms Omada is reachable.
   - `GET {api_url}/api/me` with `Authorization: Bearer {OMADA_CLERK_TOKEN}` —
     confirms the Clerk token is valid.
6. Prints `✓ All checks passed`.

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

## Tests

```bash
pytest tests/ -v --cov=src.config
```

Coverage of `src/config.py` is ≥90%. Connectivity tests use
`httpx.MockTransport` and never touch the network.
