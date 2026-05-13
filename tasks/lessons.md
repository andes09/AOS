
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

---

## Railway Dockerfile deployments do not expand shell variables in startCommand

**Pattern:** `startCommand = "uvicorn ... --port $PORT"` caused uvicorn to receive the literal string `$PORT` instead of the actual port number. Healthcheck failed with "service unavailable" and deploy logs showed `Error: Invalid value for '--port': '$PORT' is not a valid integer`.

**Root cause:** Railway runs `startCommand` in exec form (no shell) for Dockerfile-based deployments. Shell variable expansion (`$PORT`) only happens when a shell processes the command.

**Rule:** Always wrap Railway `startCommand` in `sh -c '...'` for Dockerfile deployments: `startCommand = "sh -c 'uvicorn ... --port $PORT'"`.

---

## PYTHONUNBUFFERED=1 is required in Python Docker containers

**Pattern:** Python process was crashing on startup with no output in Railway deploy logs. The error existed but was buffered in memory and never flushed before the process exited.

**Rule:** Always set `ENV PYTHONUNBUFFERED=1` in Python Dockerfiles. Without it, stdout/stderr are buffered and crash output is silently lost.

---

## Vite env vars in Docker builds require ARG/ENV declarations — check the Dockerfile first

**Pattern:** `VITE_CLERK_PUBLISHABLE_KEY` was set in Railway dashboard but the built app still had no value for it. Sent user through a redeploy cycle before identifying the root cause.

**Root cause:** Docker `RUN` commands do not inherit environment variables from the host or CI system. Railway injects env vars into the runtime container, but Vite runs at build time (`RUN npm run build`). Without an explicit `ARG` + `ENV` declaration in the Dockerfile, the variable is invisible to Vite.

**Rule:** When debugging a missing `VITE_*` variable in a Dockerized app, check the Dockerfile *first* before asking the user to redeploy. If `ARG VITE_FOO` and `ENV VITE_FOO=$VITE_FOO` are not present before `RUN npm run build`, the fix is in the Dockerfile — not the Railway dashboard.

---

## Never mix two migration systems — commit to one and stamp the DB on every manual patch

**Pattern:** The project used both `alembic upgrade head` (via `preDeployCommand`) and `migrate.py` (a custom idempotent runner). Railway cached/skipped alembic repeatedly, leaving `alembic_version` stuck at `init003`. Manual SQL patches applied directly in the Railway Data tab were never stamped in `alembic_version`, so the next deploy had no idea what was already applied. This caused cascading 422s and 500s that looked like application bugs but were really missing columns/tables.

**Root causes:**
1. Two competing migration systems — alembic and migrate.py — neither was authoritative
2. Manual DB patches (CREATE TABLE, ALTER TABLE in Railway Data tab) without updating `alembic_version`
3. Never verified `SELECT * FROM alembic_version` before debugging app-level errors

**Rules:**
1. Pick one migration system from day one and never switch mid-project without fully retiring the other
2. `migrate.py` (idempotent, bypasses alembic file-discovery) is more reliable for Railway than `alembic upgrade head` — use it as `preDeployCommand` from the start
3. Every time you manually patch the DB, immediately run: `INSERT INTO alembic_version (version_num) VALUES ('initXXX') ON CONFLICT DO NOTHING`
4. Before debugging any 4xx/5xx, run `SELECT * FROM alembic_version` first — a missing migration explains most runtime failures faster than any other check
5. Write all migrations idempotent (`IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`) so re-running is always safe

---

## Exhaust all available tools before consulting the user

**Pattern:** Repeatedly asked the user for information or to run commands that I could have handled myself using available tools (Railway CLI, psql, grep, file reads, etc.).

**Rule:** Before asking the user anything, ask yourself: "Can I answer this with a tool call?" If yes, use the tool. Only consult the user when you are genuinely blocked — missing credentials, need a product decision, or require input that no tool can provide. The user should never be a workaround for tool laziness.

---

## Use Railway CLI for DB operations — never ask the user to run SQL manually

**Pattern:** Had Railway CLI access the entire session but made the user run every SQL query manually. This caused unnecessary back-and-forth, introduced errors from partial execution, and made it impossible to verify results.

**Rules:**
1. Always use `railway variables --service Postgres --json` to get `DATABASE_PUBLIC_URL` at the start of any DB debugging session
2. Run all diagnostic and fix queries via `psql "$DATABASE_PUBLIC_URL"` directly — never paste SQL for the user to run unless they explicitly ask to
3. Wrap multi-step deletes in `BEGIN/COMMIT` to avoid partial commits when FK constraints fail mid-sequence
4. After any destructive operation, immediately verify with a SELECT — never assume "all done" from the user means the query succeeded

---

## Diagnose fully before giving SQL fixes — never drip-feed queries

**Pattern:** When debugging DB state issues, gave one diagnostic query at a time, waited for results, then gave the next query. This caused unnecessary back-and-forth and frustrated the user.

**Root cause:** Did not think through all possible failure modes upfront before asking the user to run anything.

**Rule:** Before giving any SQL fix, mentally trace ALL possible failure points: enum case, team_id mismatch, missing data, FK constraints. Run ALL diagnostic queries in one block, interpret the results, then give the complete fix SQL in one block. Never make the user run more than two rounds of queries (one diagnostic, one fix).

---

## Decouple alembic migrations from the server start command

**Pattern:** Running `alembic upgrade head && uvicorn ...` in `startCommand` caused healthcheck failures whenever the migration hung or was slow. The `&&` meant uvicorn never started if alembic failed, and the healthcheck timer ran against both operations combined.

**Rule:** Use Railway's `preDeployCommand` for migrations and `startCommand` only for the server. Migrations and server availability are independent concerns — don't couple them.

---

## Do a complete analysis before acting on pasted errors

**Pattern:** User pastes an error and I jump to the first plausible fix without considering alternatives. This leads to incorrect or unnecessary changes (e.g. changing `data=` to `json=` in oauth.py when the real cause was something else entirely).

**Root cause:** Treating error triage as a single-hypothesis problem instead of a multi-hypothesis one.

**Rule:** When the user pastes an error:
1. Read the full stack trace and identify the exact line and call that failed
2. Generate at least 2–3 distinct root cause hypotheses (config, code bug, data state, expired token, etc.)
3. Eliminate hypotheses using evidence already available (logs, DB queries, code reads) before touching anything
4. Only make a code change if the root cause is confirmed to be in the code — never speculatively modify working code to "try something"
5. If the cause is configuration or external state, say so and explain what to check — do not add code workarounds

---

## Shell state does not persist between separate Bash tool calls — always chain git operations

**Pattern:** Shell state (working directory, active git branch) does not carry over between separate Bash tool calls. Running `git checkout <branch>` in one call and then `git commit` in a subsequent call can silently commit to a different branch.

**Root cause:** Each Bash tool call starts a fresh shell. git HEAD is file-based and persists on disk, but the working directory and any shell variables are reset between calls.

**Rules:**
1. Always chain git operations with `&&` in a single Bash call: `git checkout <branch> && git add <files> && git commit -m "..."`
2. Never assume the active branch or working directory from a previous tool call is still set — always verify explicitly
3. When staging + committing, do it in one chained command to prevent branch drift between calls
4. On Windows especially: shell state does not persist at all between calls — every git operation must re-establish context in the same command

---

## Any column added to a SQLAlchemy model must exist in production Postgres before the code deploys

**Pattern:** Migration `0015` added `organizations.is_simulated` and `tickets.is_carryover` as alembic files AND as SQLAlchemy model fields, but was never added to `apps/api/migrate.py`'s `MIGRATIONS` list. Production deploy ran `migrate.py` (which stops at `0014`), so the columns were never created in prod Postgres — but the code shipped with the columns declared on the model. Every `SELECT` against `organizations` or `tickets` crashed with `column ... does not exist` because SQLAlchemy expands `Organization` into `SELECT id, ..., is_simulated, ... FROM organizations`.

**Root cause (two failures stacked):**
1. **Two parallel migration systems out of sync.** This codebase uses `migrate.py` (a hand-rolled idempotent runner) in Railway's `preDeployCommand`, not raw `alembic upgrade head`. Adding a file under `alembic/versions/` does NOT cause production to apply it. The model change shipped without the schema change.
2. **Experiment-only columns added to core product tables.** `is_simulated` and `is_carryover` exist purely for the TAWOS simulator, but they were attached to `Organization` and `Ticket` — tables every request hits. The blast radius was every API call, not just simulator code paths.

**Rules:**
1. **Any change to a SQLAlchemy model is a schema change.** Adding/removing/renaming a column requires a corresponding migration that runs against production *in the same deploy*. Never merge a model change without confirming the matching migration is in the path that production actually executes.
2. **In this repo specifically:** the production migration path is `apps/api/migrate.py`'s `MIGRATIONS` list (called via Railway `preDeployCommand`). The `alembic/versions/` directory is for local development only. Any schema change must be added to BOTH — alembic alone is invisible to production.
3. **Pre-merge checklist for model PRs:** open `apps/api/migrate.py` and confirm (a) a new entry exists in `MIGRATIONS`, (b) `HEAD` is bumped to that revision, (c) the SQL uses `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` so it's idempotent. If any of those are missing, the deploy will crash.
4. **Don't add experiment/simulator columns to core product tables.** If a feature is local/dev-only (TAWOS importer, simulator, internal tooling), the columns belong in a separate table or schema that the core API doesn't query. Attaching them to `Organization`/`Ticket`/etc. means every production request now depends on local-only schema being present.
5. **For the next outage of this shape:** the fix is fast — remove the offending columns from the SQLAlchemy models and redeploy. SQLAlchemy will stop selecting them and the crash stops immediately. The DB itself doesn't need a rollback. Do the model edit first, deploy, then clean up the orphan migration files.

