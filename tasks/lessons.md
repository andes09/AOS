
# Lessons Learned

## Always verify the git branch before dispatching subagents

**Pattern:** When creating a new branch at the start of a session (`git checkout -b <branch>`), subsequent subagent Bash calls may not inherit the switched branch. The subagents commit to whatever branch the repo HEAD was on before the checkout — often the previous session's working branch.

**Root cause:** Each Bash tool call starts a fresh shell. While git HEAD is file-based and *should* persist, subagents that `cd` into subdirectories or run git in a worktree context can commit to the wrong branch silently.

**Rule:** After every subagent commit, immediately run `git branch --show-current` to verify the branch. Add `"verify you are on <branch-name> before committing"` to every subagent prompt explicitly. If commits land on the wrong branch, cherry-pick them to the correct branch before continuing — do NOT reset or rewrite history on a shared branch.

---

## Don't make code changes for problems that are configuration issues

**Pattern:** When root cause is missing env vars / config, the fix is telling the user what to configure — not adding defensive null guards that produce the same user-visible outcome.

**Rule:** Before touching code, ask: "Does this change actually improve the user experience or just mask the same error differently?" If the answer is no, don't make the change.

---

## Always create a new branch when the prompt instructs it

**Pattern:** User explicitly asked to create a new branch in their prompt, but I started work without doing so.

**Root cause:** Did not read the full prompt before acting.

**Rule:** Read the entire prompt before taking any action. If branch creation is mentioned anywhere in the prompt, create the branch as the very first step before any implementation work begins.

---

## Write lessons to tasks/lessons.md, not just memory

**Pattern:** After a user correction, I wrote the lesson only to the memory system and skipped `tasks/lessons.md`.

**Root cause:** CLAUDE.md explicitly states to update `tasks/lessons.md` after any correction. I did not follow this.

**Rule:** After ANY correction from the user, ALWAYS write the lesson to `tasks/lessons.md`. The memory system is supplementary, not a replacement.

---

## Check infrastructure first when debugging network errors

**Pattern:** Browser showed `net::ERR_FAILED` on all authenticated API calls. Spent many steps debugging CORS headers, token expiry, JWT format, and Playwright context — when the real cause was PostgreSQL not running. The DB being down caused a 500 with no CORS headers, which the browser surfaced as `ERR_FAILED`.

**Root cause:** Started debugging at the application layer instead of the infrastructure layer.

**Rule:** When debugging `net::ERR_FAILED` or unexpected 500s, check infrastructure FIRST — DB running? External services reachable? A single connection test takes 5 seconds; chasing application-layer red herrings takes an hour.

---

## Verify both sides before touching code on a 4xx bug report

**Pattern:** A route returns 401. Assumption is frontend isn't attaching the token or backend is missing auth. Read both sides before changing anything.

**Root cause:** Jumping to a fix without tracing the full request path.

**Rule:** For any auth error, read (1) the exact component/hook making the call, (2) the `useApi()` / fetch wrapper, and (3) the route's `Depends(...)` list. Only write code if a real gap is found. If both sides are correct, the issue is configuration (wrong Clerk key, expired token, network to Clerk's verify endpoint) — not code.

---

## Warn about unmet track dependencies before proceeding to the next phase

**Pattern:** Tracks were built out of dependency order (e.g. UI and service logic built before DB models and route wiring), resulting in a frontend that calls endpoints that don't exist.

**Rule:** Before starting any new track, explicitly verify all prerequisite tracks are fully complete (not just partially done). If a dependency is unmet, stop and call it out to the user before proceeding. The plan's dependency order exists for a reason — don't skip it.

---

## Never use state as a useEffect re-run guard — use a ref instead

**Pattern:** `useProvisionOrg` used `status !== 'idle'` as a guard inside `useEffect`. React Strict Mode double-fires every effect: first invocation sets `status='loading'` and gets cancelled; second invocation sees `status='loading'` and exits early; first request resolves but `cancelled=true` so state never updates. App stuck on loading forever.

**Root cause:** State read inside an effect is a stale closure. Strict Mode cancels the first invocation before it can resolve, and the second invocation reads the stale state value.

**Rule:** When you need to track "has this already run" inside a `useEffect`, use a `useRef`, not state. Refs are mutable and shared across all invocations of the effect — they are immune to stale closure issues. State is the wrong primitive for this.

---

## Write an initial migration for the full base schema, not just incremental ones

**Pattern:** Only an incremental migration (`0001_add_sprint_alerts`) existed. On a fresh DB, it failed immediately because the base tables (`sprints`, `teams`, etc.) didn't exist — there was no `0000` migration to create them.

**Root cause:** Base schema was created some other way (direct DB manipulation or `create_all`) and was never captured in a migration file.

**Rule:** Every project must have a `0000_initial_schema` migration that creates all base tables. When setting up a new DB from scratch, `alembic upgrade head` must be the only command needed. If it isn't, write the missing base migration immediately.

---

## CORS origin must match the actual frontend port

**Pattern:** `.env` had `FRONTEND_URL=http://localhost:5174` but the frontend was running on `5173`. Every API call was blocked by CORS with no useful error beyond `ERR_FAILED`.

**Root cause:** Port mismatch between env config and the actual Vite dev server port.

**Rule:** After starting the frontend, confirm the actual port in the terminal output and verify it matches `FRONTEND_URL` in `.env` before debugging anything else.

---

## Plan for the missing base migration when a fresh DB is needed

**Pattern:** Alembic migrations assumed tables existed that had never been migrated. The error (`relation "sprints" does not exist`) only appeared at runtime, not during development.

**Root cause:** The developer who wrote `0001` had an existing DB with the tables already present. A fresh install exposed the gap.

**Rule:** When writing an incremental migration, always ask: "Would `alembic upgrade head` on a brand-new empty DB succeed?" If not, write the base migration first.

---

## useEffect logic bugs in React are easy to miss — trace all state combinations explicitly

**Pattern:** The `OrgProvider` component had `if (!isLoaded || (!provisioned && !error))` which made the error state unreachable (when `error=true`, the condition was `false` and children rendered). The no-org state was also unreachable because the loading check came before the org check.

**Root cause:** The condition was written for the "happy path" without tracing what happens when `error=true` or `organization=null`.

**Rule:** For any multi-state React guard, write out every combination of state values and trace which branch each hits. If any reachable state hits the wrong branch, the logic is wrong. Separate guards (sequential `if` statements) are almost always clearer than compound boolean conditions.

---

## Define the API contract before building frontend and backend in parallel

**Pattern:** Frontend and backend were built in separate tracks/sessions without agreeing on endpoint paths, request/response shapes, or OAuth flow design upfront. The backend used `/api/integrations/jira/connect` with a backend-callback OAuth flow; the frontend called `/api/jira/oauth/initiate` with a frontend-callback flow. Neither side read the other's code. The router was also never registered in `main.py` because no one owned the integration step.

**Root cause:** Parallel track development without a shared API contract. Each side made independent, reasonable assumptions that turned out to be incompatible.

**Rule:** Before any track writes code that crosses the frontend/backend boundary, the plan must specify: exact endpoint paths, HTTP methods, request/response shapes, and — for OAuth — which party (frontend or backend) receives the provider callback. Both sides must read and agree on this contract before implementation starts. The plan should also explicitly assign ownership of the "wire everything together" step (registering routers, wiring providers, etc.).

---

## Smoke test migrations locally before deploying

**Pattern:** Alembic revision IDs `'0000'`/`'0001'`/`'0002'` caused alembic to skip the base migration silently on Railway, requiring 6+ deploy attempts and 3 DB resets to diagnose. The root causes (all-zero revision IDs treated as falsy, a hidden third migration file) would have been caught in under 2 minutes locally.

**Root cause:** Never ran `alembic upgrade head` against a fresh local DB before deploying. Also only fixed the files I knew about without checking how many migration files existed total.

**Rules:**
1. Before any deployment, run `alembic upgrade head` against a clean DB locally (or via Docker) and verify all migrations apply without error.
2. When editing migration revision IDs, `Glob` all migration files first — fix every file in one pass before committing.
3. When Railway deploy logs show `Running upgrade  -> <rev>` with a blank before `->`, it means alembic is treating that revision as the base (no parent). This is a broken revision chain, not a DB state issue — fix the code, don't reset the DB.
4. Use alphanumeric revision IDs (e.g. `init001`, `init002`) — never all-zero strings like `'0000'`. Alembic's internal logging does `down_revision or ""` which makes zero-like strings ambiguous.

---

## Verify Railway branch before deploying

**Pattern:** Spent multiple deploy cycles before discovering Railway was deploying from `main` instead of `feat/onboarding`. All our fixes were on the feature branch and never reached the deployed build.

**Root cause:** Did not confirm which branch Railway was tracking at the start of the deployment session.

**Rule:** At the start of any Railway deployment session, immediately verify Railway → service → Settings → Source shows the correct branch. Confirm the deployed commit hash matches the latest local commit before debugging any runtime errors.

---

## Committed code must be self-contained — don't leave prerequisites uncommitted

**Pattern:** `apps/api/src/auth.py` was refactored (required for the new tests to mock correctly) but left uncommitted while `test_organizations.py` was committed. The committed code silently depended on the uncommitted refactor.

**Root cause:** The auth refactor was treated as a separate concern and not staged with the feature commit.

**Rule:** Before committing, run `git status` and ask: "Does any uncommitted file affect the correctness or testability of what I'm about to commit?" If yes, commit it together or first.

