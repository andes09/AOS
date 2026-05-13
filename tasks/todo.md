# Simulator Config Foundation — Spec Re-Alignment

Branch: `simulator-config-foundation` (fresh, cut from `release`)

## Context
An earlier iteration of this directory was merged into `release` and
referenced `is_simulated` on the Organization payload. That field was
removed from prod after the outage captured in `tasks/lessons.md`
("Any column added to a SQLAlchemy model must exist in production
Postgres before the code deploys"). The new spec drops those checks
entirely. We are rewriting to the new spec.

## Plan

- [x] Inspect existing files — confirmed divergences.
- [x] Create fresh `simulator-config-foundation` branch (old, fully-merged
      branch deleted with user approval).
- [ ] Rewrite `config/environments/local.yaml` to match spec exactly
      (remove `max_real_users_in_org`, `require_simulated_org`; add
      `refuse_with_message: null`).
- [ ] Rewrite `config/environments/sims.yaml` similarly.
- [ ] Rewrite `config/environments/prod_blocked.yaml` similarly
      (empty `required_url_substrings` and `block_url_substrings`,
      `refuse_with_message` set, no `max_real_users_in_org`).
- [ ] Leave `config/teams/stage1_team.yaml` as-is (already matches spec).
- [ ] Rewrite `src/config.py`:
  - [ ] `SafetyConfig` keeps only the 4 spec fields.
  - [ ] `verify_connectivity` does `/health` (200) then `/api/me`
        (200, 401 → expired-Clerk message, else print body).
  - [ ] Drop `max_real_users_in_org` and `require_simulated_org` logic
        and any `is_simulated` references.
  - [ ] Banner shows only `allow_production={value}` (no max_users).
- [ ] Update `src/main.py` order to match spec:
      `load_environment → load_secrets → validate_safety → banner →
       asyncio.run(verify_connectivity) → success print`.
- [ ] Rewrite `tests/test_config.py` to cover the 10 spec-named tests
      plus connectivity tests via `httpx.MockTransport` against
      `/api/me`. Target ≥90% coverage of `src/config.py`.
- [ ] Verify `pyproject.toml`, `.env.example`, `.gitignore` against spec
      (current versions are very close — only minor edits if needed).
- [ ] Update `README.md` to drop references to org-count /
      `is_simulated` and to describe the `/api/me` flow.
- [ ] Run `pytest tests/ --cov=src` and confirm ≥90% on src/config.py.
- [ ] Run `python -m src.main --check-env --env prod_blocked` —
      expect immediate refusal, zero HTTP.
- [ ] Run `python -m src.main --check-env --env typo` —
      expect FileNotFoundError listing valid envs.
- [ ] Commit in 7 chunks per spec.
- [ ] Confirm with user before merging to main or pushing.

## Out of scope
- Simulator behavioral logic (Jira driver, observer, dev model, orchestrator).
- Connecting to real Jira.

## Review

### What landed (5 commits on `simulator-config-foundation`)

| Commit  | Subject                                         |
| ------- | ----------------------------------------------- |
| 3e0a325 | feat: env yaml files local, sims, prod_blocked  |
| 428577f | feat: src/config.py pydantic config loading     |
| 2173f61 | feat: --check-env cli command                   |
| ba7b000 | test: config loading and safety validation      |
| 6d5923c | docs: readme for simulator config               |

The spec's 7-commit plan included scaffolding and a team config commit.
Both files (`pyproject.toml`, `config/teams/stage1_team.yaml`) were
already on `release` from the prior iteration and already match the
spec verbatim, so there was no diff to capture. The 5 commits above
cover every actual code change.

### Spec acceptance criteria

- ✅ `python -m src.main --check-env --env prod_blocked` —
  prints the refusal message; zero HTTP calls (refusal happens in
  `validate_safety`, before `verify_connectivity` is reached).
- ✅ `python -m src.main --check-env --env typo` —
  `FileNotFoundError` with `['local', 'prod_blocked', 'sims']` listed.
- ✅ `python -m src.main --check-env --env local` (with Omada not
  running locally) — fails cleanly with the spec-mandated message
  *"Omada not running at http://localhost:8000. Start with uvicorn
  src.main:app --reload from apps/api."*
- ✅ `pytest tests/ --cov=src.config` — 22/22 pass, 98% coverage.
- ✅ `.env.example` exists with placeholders; `.env` is gitignored.
- ✅ `README.md` updated to drop org-count / `is_simulated` references.

### Notes

- The `.gitignore` line `output/*` (rather than `output/`) is kept from
  the prior iteration because git can't un-ignore a file inside a
  fully-ignored directory. The spec's literal text would silently
  ignore `output/.gitkeep`; `output/*` + `!output/.gitkeep` does what
  the spec intends.
- The CLI flow puts `load_secrets()` immediately after
  `load_environment()`, per spec. This means a `.env` with missing keys
  will error before `validate_safety` runs for any env, including
  `prod_blocked`. The acceptance criterion ("immediately refuses with
  the configured message") is satisfied for users who have a populated
  `.env` (which is the documented setup).

### Not yet executed (awaiting user)

- `git checkout main && git merge simulator-config-foundation`
- `git push origin main`
- `git checkout release && git merge main && git push origin release`
