# Railway migration checklist

One-time steps to flip production deploys from `main` to `release`. Do these in the Railway dashboard — none of it can be done from code.

## Before you start

- [ ] Confirm `release` branch exists on `origin`. If not, create it from the current production SHA: `git checkout -b release <sha> && git push origin release`.
- [ ] Verify `release` is in sync with `main` (or with the SHA currently deployed). Mismatches will redeploy unintended commits as soon as you flip the watch branch.

## Railway: API service

1. [ ] Open the API service in the Railway dashboard.
2. [ ] Go to **Settings → Source**.
3. [ ] Change the **Deploy branch** from `main` to `release`.
4. [ ] Save. Railway will *not* redeploy until the next push to `release`.
5. [ ] Go to **Variables**.
6. [ ] Confirm `ENVIRONMENT=production` is set. Add it if missing.
7. [ ] Confirm all other required vars are present: `DATABASE_URL`, `DATABASE_URL_SYNC`, `REDIS_URL`, `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, `CLERK_WEBHOOK_SECRET`, `ENCRYPTION_KEY`, `FRONTEND_URL`, `API_URL`, `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`, `JIRA_REDIRECT_URI`.

## Railway: Web service

1. [ ] Open the web service in the Railway dashboard.
2. [ ] **Settings → Source → Deploy branch** → change from `main` to `release`.
3. [ ] Save.
4. [ ] **Variables** — confirm `VITE_API_URL` and `VITE_CLERK_PUBLISHABLE_KEY` are set.

## GitHub branch protection

1. [ ] Go to **GitHub → Settings → Branches**.
2. [ ] Add a protection rule for `release`:
   - [ ] Require PR before merge (or restrict pushes to admins for hotfix-by-direct-commit flow)
   - [ ] Require status checks to pass
   - [ ] Do **not** allow force pushes
   - [ ] Do **not** allow deletion
3. [ ] Update the rule on `main`: remove any "ships to production" warnings in PR templates — `main` is now integration-only.

## First production deploy from `release`

1. [ ] Locally: `git checkout release && git fetch origin && git merge --ff-only origin/main && git push origin release`.
2. [ ] Watch Railway: both services should redeploy.
3. [ ] Once green, hit `https://<api-host>/health` — expect `{"status": "ok", "environment": "production"}`.
4. [ ] Sign in to the web app as a real user. Confirm:
   - [ ] No "Push to Jira" button (flag off)
   - [ ] No "Multi-Team" nav item (flag off)
   - [ ] No "Exec Dashboard" nav item (flag off)
   - [ ] Visiting `/app/exec-dashboard` directly redirects to `/app`
5. [ ] Hit `GET /api/features` (authenticated). Expect `environment: "production"` and the flag set from `production.yaml`.

## Rollback plan

If the `release` deploy breaks production:

1. [ ] In Railway, **Deployments → Rollback** to the previous successful deploy. This is faster than reverting via git.
2. [ ] Investigate the bad commit on `release`. Fix on a branch off `main`, merge to `main`, then fast-forward `release` again.

## Post-migration cleanup

- [ ] Update internal docs / runbooks that say "push to main to ship".
- [ ] Tell the team: `main` no longer ships. Use the fast-forward-release flow from `DEPLOYMENT.md`.
