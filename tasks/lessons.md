
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

## Warn about unmet track dependencies before proceeding to the next phase

**Pattern:** Tracks were built out of dependency order (e.g. UI and service logic built before DB models and route wiring), resulting in a frontend that calls endpoints that don't exist.

**Rule:** Before starting any new track, explicitly verify all prerequisite tracks are fully complete (not just partially done). If a dependency is unmet, stop and call it out to the user before proceeding. The plan's dependency order exists for a reason — don't skip it.

