# Lessons Learned

## Don't make code changes for problems that are configuration issues

**Pattern:** When root cause is missing env vars / config, the fix is telling the user what to configure — not adding defensive null guards that produce the same user-visible outcome.

**Rule:** Before touching code, ask: "Does this change actually improve the user experience or just mask the same error differently?" If the answer is no, don't make the change.
