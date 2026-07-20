# Omada — Active Work

---

## 🚀 ACTIVE — Planner Revamp (team lanes, time blocking, design system)

Rebuild the planner from a bare Mon–Fri checkbox grid into a dense, color-coded
scheduling surface: team-member lanes down the left, time-labelled task blocks
laid out chronologically. Stays org/team-scoped — lanes are people, not life
areas. Task color derives strictly from the assignee; unassigned work is grey.
Full plan: `~/.claude/plans/iridescent-soaring-hippo.md`.

**Phase 1 — Design system (frontend only, unblocked)**
- [x] `tokens.css`: define missing `--color-border-strong`; add spacing scale, z-index scale, and the 10-hue lane palette (light + dark)
- [x] `lib/laneColors.ts` — `laneVars()` as the single color decision point
- [x] `lib/date.ts` — move date helpers out of `PlannerCalendarPage`, add wall-clock time helpers
- [x] `styles/planner.css` — pseudo-selectors/keyframes only (imported from `index.css`)
- [x] `ui/`: `Avatar`, `IconButton`, `SegmentedControl`, `Tooltip` + barrel exports; `Modal` adopts `--z-modal`
- [x] Add Vitest (scoped to `src/`, so it doesn't swallow the Playwright suite) + 54 tests for the pure modules

**Phase 2 — Backend** (code complete; migration NOT yet run against a real DB)
- [x] Migration `0031_planner_attribution`: `tasks.assignee_id` (FK developers, ON DELETE SET NULL), `tasks.scheduled_time` (naive TIME), `tasks.duration_minutes`; `developers.color_index` (server_default), `developers.avatar_url`; backfill distinct color_index per team
- [x] `models/task.py` + `models/developer.py` matching columns
- [x] `_owned_developer()` helper — org-scope assignee validation (cross-tenant guard, tested)
- [x] `GET /api/roadmap/members` (single query, correlated count — no N+1)
- [x] Extend `PATCH /tasks/{id}` with assignee/time/duration via the `model_fields_set` idiom
- [x] `POST /api/roadmap/tasks` (lane "+" button) and `POST /api/roadmap/tasks/reschedule` (bulk; all-or-nothing)
- [x] `_task_json` gains the three new fields
- [x] **Ran `alembic upgrade head` against local Postgres (2026-07-19).** Verified: all 5 columns present; `scheduled_time` is `time without time zone` (naive, as intended); FK delete rule is `SET NULL`; both indexes created; color backfill correct; `alembic_version` holds exactly one row (`0031`)
- [ ] Optional: `alembic downgrade -1` then up again to prove reversibility. The downgrade compiles to correct SQL offline but has not been executed — deliberately not run against the active dev DB unprompted, since it drops columns

**Phase 3 — Sidebar + attribution**
- [x] `PlannerSidebar`, `MemberLane` (unassigned lane is the same component with `colorIndex: null`), assignee chips in the detail modal; `laneVars()` drives every card color; assignee filtering via lane click

**Phase 4 — Time model**
- [x] `PlannerPage` replaces `PlannerCalendarPage` (route updated, old file deleted); `usePlannerData`, `usePlannerMutations`, `plannerCache`, `plannerFilters`, `taskLayout`
- [x] `TimeAxis`/`HourGrid`, `DayColumn`, `PlannerToolbar`, duration presets in the modal
- [x] **Overlap decided: side-by-side column split**, not "+2 more" (see review)

**Phase 5 — Drag and drop (@dnd-kit)**
- [x] Draggable tasks; `slot:` (15-min), `day:` (all-day strip), `lane:`, `unscheduled` droppables; `PointerSensor` distance:5; `DragOverlay` at `--z-drag-overlay`

**Phase 6 — Views + detail modal**
- [x] `SegmentedControl` view switcher, day/week via shared `CalendarGrid`, `ListView`, `BoardView`, `UnscheduledTray`, `TaskDetailModal`, search filter
- [ ] Bulk "assign selected → person" (needs multi-select; `rescheduleTasks` mutation is already wired for it)

**Phase 7 — Polish**
- [ ] Wire `useProjectChat` to a chat panel; keyboard nav; Playwright specs (assign → reload → color persists; drag → reload → time persists)

### Review — Phase 1 (2026-07-19)

**Shipped.** 54 Vitest tests green, `tsc --noEmit` clean, prod build succeeds.
Phase 1 is behaviour-neutral by design — no component renders differently yet.

Two things found along the way that were *not* in the plan:

1. **`--color-border-strong` was referenced but never defined** (`PlannerCalendarPage.tsx:290`), so the task checkbox border had been silently falling through its `var()` fallback. Now defined in both themes.
2. **`apps/web`'s typecheck was already broken on main — 85 errors**, all "cannot be used as a JSX component" on lucide-react/react-router. Root `package.json` pins `@types/react` to v18 under a `pnpm.overrides` key that **pnpm 11 no longer reads** (it warns on every install), so `@types/react@19` leaked in from LandingPage (which legitimately runs React 19). Since `build` is `tsc && vite build`, the web build was failing on main. Fixed by mirroring the overrides into `pnpm-workspace.yaml` (pnpm 11's new home). Verified both `apps/web` and `LandingPage` typecheck at 0 errors afterwards. **The duplicate block in root `package.json` was left in place deliberately** — `engines` still allows pnpm ≥9, which reads the old location and ignores the new one. Keep the two in sync until the repo drops pnpm <11.

### Review — Phases 2–6 (2026-07-19)

**Shipped.** Backend: 15 new tests green (`tests/test_roadmap_planner.py`), full suite 344 passed / 24 failed — the same 24 that fail on a clean tree (verified by stashing). Frontend: 82 Vitest tests green, `tsc --noEmit` clean, prod build succeeds.

**Phase 2 caveat:** the migration is written and compiles to correct SQL offline (`alembic upgrade 0030:0031 --sql` — note it emits `TIME WITHOUT TIME ZONE`, i.e. naive, as intended), but has **not been run against a real database**. The endpoint tests all pass against in-memory SQLite via the existing `tmp_db` fixture, so behaviour is proven; only the DDL round-trip and the color backfill are unverified.

**Overlap handling — decided.** Two tasks at the same hour render **side by side at half width**, via a greedy interval-graph column pack in `taskLayout.ts`. Chose this over "+2 more" because a scheduling conflict is precisely what the user needs to see, and hiding it behind a disclosure defeats the purpose of a time grid. Clusters are computed per connected run of overlaps, so a 3-way pileup at 09:00 doesn't shrink an unrelated 14:00 task. 13 tests cover the geometry.

**Deviations from plan:**
- `WeekView` + `DayView` collapsed into one `CalendarGrid` — they differed only in column count, so two files would have been duplicated code. Day view passes `dayCount: 1`.
- `TimedTaskCard` merged into `TaskCard`. Positioning is supplied by the caller via `style`, so one card component serves the grid, sidebar, list, board, and tray. Avoids two components drifting apart.
- `AssigneePicker` / `DurationPicker` live inside `TaskDetailModal` as local chip components rather than separate files — they have no second call site yet.
- Single-task drags go through `updateTask`, not `rescheduleTasks`. The bulk mutation is wired and tested but waits for multi-select.

**Known gaps:** no Playwright coverage for the planner yet; bulk assign needs multi-select; `useProjectChat` is still unconsumed.

---

## 🐛 Known issues / small follow-ups

- [ ] `apps/web/tests/e2e/onboarding-v2.spec.ts` — the purpose-step test uses a
      stale locator: `getByRole('button', { name: /A startup/ })`, but
      `PurposeStep.tsx` renders the three purpose choices as `role="radio"`
      (a `radiogroup`, not buttons). Update the locator to `getByRole('radio', ...)`.
      Found 2026-07-20 while verifying the legacy-onboarding-removal branch;
      confirmed via `git diff origin/main` that neither file was touched by
      that change, so it predates it and is a pure test-locator bug.
- [ ] Onboarding v2 — Ops (external, not code): GitHub OAuth apps per env
      (callback `/api/integrations/github/callback`), Clerk GitHub social
      provider, `GITHUB_*` + `ANTHROPIC_API_KEY` in Railway. Blocks
      onboarding v2 going live in production (flag is currently off there).

---

## ✅ Done (archived)

- **Pivot: Onboarding v2 (project roadmap AI)** — shipped 2026-07-13. Replaced the Jira onboarding entry with GitHub connect → profile → purpose classification (hobby/startup/learning) → LLM idea interview (`services/idea_interview.py`, SSE streaming, 40-msg cap). Headless hooks layer at `features/onboarding-v2/` + reference UI `OnboardingV2Page.tsx`. 45 backend tests + 3 Playwright green; partner integration doc at `docs/onboarding-v2-frontend-integration.md`. Outstanding: GitHub OAuth ops config, tracked above.

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

Nothing active beyond what's tracked above. Next work items are billing (configure + launch) and whatever comes after.
