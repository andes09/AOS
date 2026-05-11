# Deployment

How Omada moves from local dev to production, and how features are gated along the way.

## Branches and environments

| Branch                          | Environment   | Purpose                                                |
| ------------------------------- | ------------- | ------------------------------------------------------ |
| `main`                          | local only    | Integration trunk. Pushes to `main` no longer deploy.  |
| `release`                       | production    | Production deploy branch. Railway watches this branch. |
| `feat/*`, `fix/*`, `infra/*`    | local only    | Short-lived branches. Merge into `main` via PR.        |

`ENVIRONMENT=local` is the default. Production sets `ENVIRONMENT=production` in Railway.

## Workflow

1. Branch off `main` for any change: `git checkout -b feat/whatever`.
2. Open a PR into `main`. Merging into `main` ships nothing to users — it just integrates.
3. To ship to production, fast-forward `release` to the desired `main` SHA and push `release`. Railway redeploys.

```bash
# from a clean checkout of main
git fetch origin
git checkout release
git merge --ff-only origin/main
git push origin release
```

If `release` cannot be fast-forwarded, something has been committed directly to `release` — investigate before forcing.

## Feature flags

Feature flags are YAML files, one per environment, at `apps/api/config/features/<environment>.yaml`. They control whether code paths and UI surfaces are visible.

- `apps/api/config/features/local.yaml` — all flags `true` for development
- `apps/api/config/features/production.yaml` — minimal surface (only `retro_pattern_detection: true` at present)

The backend loads the file matching `settings.environment` at request time. The frontend reads `GET /api/features` (Clerk-authenticated) and caches the result in TanStack Query.

### Backend gating

```python
from src.config import settings

if not settings.is_feature_enabled("push_to_jira"):
    raise HTTPException(status_code=404, detail="Feature not available")
```

`404` is intentional — disabled features should be indistinguishable from missing routes.

### Frontend gating

```tsx
import { useFeature } from './featureFlags'

const canPushToJira = useFeature('push_to_jira')
{canPushToJira && <PushToJiraButton />}
```

For whole routes, wrap with `<RequireFeature flag="exec_dashboard">…</RequireFeature>`.

## Enabling a flag in production

1. Edit `apps/api/config/features/production.yaml`, set the flag to `true`.
2. Open a PR into `main`. Get it reviewed and merged.
3. Fast-forward `release` to the new `main` SHA and push.
4. After deploy, verify the flag in the UI for a real user.

## Disabling a flag in production

Same flow as enabling — flip to `false`, merge to `main`, fast-forward `release`.

Hotfix path: if a flag must be flipped urgently, commit directly to `release`, push, then back-port to `main`.

## Current flags

| Flag                       | Local | Production | Notes                              |
| -------------------------- | ----- | ---------- | ---------------------------------- |
| `push_to_jira`             | true  | false      | Jira write surface                 |
| `scope_check_v2`           | true  | false      | New scope-cop algorithm            |
| `multi_team_dashboard`     | true  | false      | Multi-team management UI           |
| `exec_dashboard`           | true  | false      | Sector overview / exec view        |
| `data_collection_phase`    | true  | false      | Verbose telemetry collection       |
| `retro_pattern_detection`  | true  | true       | Live retro analysis                |
| `skill_based_assignment`   | true  | false      | Ticket auto-assignment by skill    |
