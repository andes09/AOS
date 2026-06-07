# Omada — Active Work

---

## ✅ Done (archived)

- **Stage 2 Simulator (M1–M6)** — multi-team matrix, all archetypes, parallel execution, HTML report. 89 tests passing. See `omada-simulator/docs/STAGE2_HOWTO.md`.
- **Stage 2 Bug fixes (2026-05-20)** — omada_team_id clobber (A), push 409s (B), missing audit logs (C), backlog sync gap (D), Celery worker (E). Large/omada flipped 33% → 50% after Fix A.
- **Initiative A — Identifier Associations** — merged. Team glossary, skill-intensity vectors, Sprint Brain routing, Scope Cop 5th criterion, override capture + recalibration loop, sprint-close refresh hooks.
- **Initiative B — Inline Ticket Refinement** — merged (waves 0–4). Scope Cop suggested revisions, Jira write integration, conflict detection, Plan Review Modal, Sign-off Carousel, batched commit, telemetry.

---

## 🔧 Billing (branch: `feat/stripe-billing`) — configure before launch

All code is written and committed. Nothing to build yet — just configuration tasks when ready to go live.

### Configure Stripe
- [ ] Form LLC + open Mercury business account (do before first charge)
- [ ] Create Stripe account under business entity
- [ ] Create 3 products + recurring prices in Stripe dashboard:
  - Starter — $159/mo + $129/mo annual
  - Team — $269/mo + $219/mo annual
  - Growth — $429/mo + $349/mo annual
- [ ] Add env vars to Railway (production):
  ```
  STRIPE_SECRET_KEY=sk_live_...
  STRIPE_WEBHOOK_SECRET=whsec_...
  STRIPE_PRICE_STARTER=price_...
  STRIPE_PRICE_TEAM=price_...
  STRIPE_PRICE_GROWTH=price_...
  ```
- [ ] Register webhook endpoint in Stripe dashboard → `https://<api-domain>/api/billing/webhook`
  - Events to enable: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`

### Merge + deploy
- [ ] Merge `feat/stripe-billing` into main
- [ ] Run migration `0016_billing` on production DB
- [ ] Flip `billing: true` in `apps/api/config/features/production.yaml`
- [ ] Smoke test: hit `GET /api/billing/status` → `{status: "free", tier: null}`
- [ ] Smoke test: create a checkout session → confirm redirect to Stripe works
- [ ] Smoke test: use Stripe CLI (`stripe listen --forward-to .../api/billing/webhook`) to fire test event → confirm org subscription updates

---

## 📋 Up next

Nothing active — both major initiatives are shipped. Next work items are billing (configure + launch) and whatever comes after.

### Post-beta — Multi-board / switch-board support

Removed from beta Settings on 2026-06-07 in favour of "one board, set during onboarding." Bring back for main release.

- [ ] Decide model: one team = one board (with a "switch" replace flow) vs. one team = many boards (with per-board scoping in queries)
- [ ] Settings: add board chip + "Switch board" action (re-opens the board picker, then triggers a full re-import or board-scoped swap depending on the model above)
- [ ] If multi-board: add board selector to DashboardLayout header next to the sync control; scope every Jira-backed query by `board_id`
- [ ] Migration impact: `sprints`, `tickets`, `team_members` may need `board_id` if going multi-board
- [ ] Handle orphaned data when a board is removed (archive vs. cascade-delete — probably archive for retro/velocity continuity)

---

## 🚀 Initiative C — Sprint Gen Speed

**Deferred:** Consent + training-data capture (Phases 2-4 below) — paused pending user research on GDPR/CCPA/privacy law.

### Phase 1 — Speed ✅ shipped (2026-06-02)

- **1a. Prompt caching** — both Claude calls now mark `system`+`tools` (and stable user prefix on assignment call) as `cache_control: ephemeral`. Within a planning session, what-if and re-plan hit cache_read on the heavy prefix.
- **1b. Complexity cache** — new table `ticket_complexity_cache` (alembic 0023), content-hashed; `_analyse_ticket_complexity` partial-fills and skips the Claude call entirely when all tickets hit.
- **1c. SSE streaming** — `/plan` accepts `Accept: text/event-stream` and emits `stage` events (complexity_start/done, assigning_start/done, enrichment_start/done) then a final `result` (or `error`). JSON path preserved for backward compat. Frontend `SprintPlannerPage` consumes the stream and shows a stage chip.

### ⏸️ DEFERRED — Phases 2-4 below paused pending privacy-law research

### Phase 2 — Consent UI

**2a. Backend consent model** (alembic 0024)
- [ ] Add to `teams`: `data_training_consent BOOLEAN NOT NULL DEFAULT TRUE`, `consent_granted_at TIMESTAMPTZ`, `consent_revoked_at TIMESTAMPTZ NULL`
- [ ] Default consent_granted_at to NOW() for new teams (since opt-out default = consent implicit on team creation)
- [ ] Existing teams: backfill `consent_granted_at = created_at` in migration (treats existing users as having consented when they signed up — acceptable for opt-out model, document the choice)
- [ ] New endpoint `PATCH /api/teams/{id}/consent` — body `{consent: bool}` — sets/clears the timestamps appropriately

**2b. Onboarding checkbox** (ReviewStep)
- [ ] Add a new `<section>` between Privacy note and Footer nav
- [ ] Checkbox (defaults checked), short copy: "Help improve Omada by sharing anonymous sprint-planning patterns. We never store ticket text, names, or descriptions — only structural data like story points and skill match scores. Change anytime in Settings."
- [ ] Pipe `consent` value through `onDone` → team-setup save payload → backend writes to teams table

**2c. Settings toggle**
- [ ] Add "Data & Privacy" section to SettingsPage with the same toggle
- [ ] On toggle: PATCH endpoint, success toast, "We'll stop collecting new training data" / "Thanks — your data helps us improve"
- [ ] Show last-changed timestamp underneath

### Phase 3 — Training data capture

**3a. Training table** (alembic 0025)
- [ ] New table `sprint_generation_traces`:
  - `id UUID PK, team_id UUID FK, sprint_id UUID FK NULL, generated_at TIMESTAMPTZ`
  - `model TEXT, prompt_version TEXT` — so we can filter by model when training
  - `input_features JSONB` — see schema below
  - `output_features JSONB` — see schema below
  - `cost_usd NUMERIC, latency_ms INT, cache_hit_pct REAL` — performance telemetry
- [ ] Indexes: `team_id`, `generated_at`, `model`

**3b. Input features schema** (structured only)
```json
{
  "team": {
    "size": 6,
    "sprint_length_days": 14,
    "developers": [
      {"dev_hash": "sha256(team_id+dev_id)", "velocity_avg": 8.2, "sprints_recorded": 6,
       "skill_vector": {"sql": 0.9, "java": 0.3}, "capacity_pts": 13}
    ]
  },
  "candidates": [
    {"ticket_hash": "sha256(team_id+ticket_id)", "story_points": 5,
     "complexity_score": 0.7, "skill_vector": {"sql": 0.8}, "matched_identifier_count": 3}
  ],
  "context": {"recent_override_count": 2, "active_retro_pattern_count": 1}
}
```
- Note: dev_hash and ticket_hash are team-scoped so re-identification requires team-level access. Skill labels are stored as-is (e.g., "sql", "auth") — they may contain product-specific terms but no PII.

**3c. Output features schema**
```json
{
  "assignments": [
    {"ticket_hash": "...", "dev_hash": "...", "confidence": 0.85,
     "skill_match_score": 0.88}
  ],
  "confidence_score": 0.82,
  "warnings_count": 1,
  "what_if_dropped": {"ticket_hash": 0.87}
}
```
- ❌ Excluded: `reasoning` text, `skill_match_reasoning` text, `summary` text, ticket titles, dev names. Reasoning text can leak ticket context ("matches the Acme refactor") so it's filtered before insert.

**3d. Write path** — `services/training_trace.py`
- [ ] New `record_generation_trace(...)` called from `create_sprint_plan` after assignments computed
- [ ] **Gated by `team.data_training_consent`** — if false, no insert
- [ ] Scrubber utility `_to_training_features(input, output)` strips text fields and hashes IDs
- [ ] Wrapped in try/except so failure never breaks user flow

**3e. Override events as preference labels**
- [ ] Link existing `SprintPlanOverride` to traces via new column `generation_trace_id UUID NULL FK`
- [ ] Set during `create_sprint_plan` response: include `trace_id` in payload; frontend echoes it when override is recorded
- [ ] Result: every override row pairs with the trace that produced the original assignment → DPO-style pair ready

**3f. Sprint outcomes capture**
- [ ] In sprint-close hook (find it — `sprint_close` or similar), for each trace where `sprint_id` is set:
  - Compute: tickets_completed_count, tickets_spilled_count, points_completed, points_spilled, override_count
  - Write to new table `sprint_outcomes (trace_id PK FK, ...metrics)` or extend traces row
- [ ] Result: structured label for "did this plan actually work out"

### Phase 4 — Privacy + ops hygiene

- [ ] Document the data model in `docs/PRIVACY.md`: what we store, what we don't, retention policy
- [ ] Add retention job (cron or Celery beat): delete traces older than 18 months (configurable)
- [ ] Add admin endpoint `DELETE /api/teams/{id}/training-data` for GDPR-style requests
- [ ] Update marketing site privacy policy copy (track as separate task — not code)

### Verification (Phase 1)
- [ ] Time a full generation before/after — log latency delta to demonstrate
- [ ] Verify `cache_read_tokens` shows up in cost_tracker logs on warm runs
- [ ] Manually clear `ticket_complexity_cache` rows for one team → confirm fallback to Claude call works
- [ ] SSE: open dev console, confirm event stream emits stage events; verify JSON fallback still works for tests
- [ ] Existing test suite passes; add focused tests for cache hit path + cache miss path

### Out of scope (intentionally)
- Actually building/training the NN — separate initiative once data accumulates
- Per-stage timing on the existing cost_tracker logs (nice-to-have, defer)
- Parallelizing Scope Cop's Jira fetches (separate quick win)
- Decomposing the assignment monolith (architectural — separate plan)

