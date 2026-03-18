
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

