# Design: Track E Velocity API Routes

**Date:** 2026-03-11
**Branch:** track-e-velocity-routes
**Status:** Approved

## Problem

Track E services (profiler, capacity, confidence) exist but have no HTTP surface. The frontend cannot access velocity or capacity data.

## Solution

Three read-only endpoints in a new `routers/velocity.py`, protected by Clerk JWT, scoped to the authenticated organisation.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/teams/{team_id}/velocity` | Per-developer velocity profiles for the team |
| GET | `/api/teams/{team_id}/velocity/{developer_id}` | Single developer profile |
| GET | `/api/teams/{team_id}/capacity` | Sprint capacity for all developers |

## Auth & Org Scoping

- All routes depend on `get_current_org_id` (new auth.py function, extracts Clerk `org_id` claim)
- `_resolve_team` shared dependency: resolves `clerk_org_id` → `Organization` → `Team`; 404 if team does not belong to authenticated org

## Data Sources

- **Velocity:** `DeveloperVelocityProfile` DB rows (pre-computed). Grouped by developer, averaged across domains per ticket_type.
- **Capacity:** `CapacityModel().model(sprint_meta, [], [])` called with active sprint calendar; PTO/meeting lists are empty (not in DB yet — MVP placeholder).
- **Confidence score:** Derived from coefficient of variation (`std_dev / mean_completion_days`); `None` if `sprint_count < 3`.

## Key Rules

- `is_sufficient_data = sprint_count >= 3`
- Confidence score and AI recommendations suppressed when `is_sufficient_data = false`
- All queries scoped to org — cross-org data leakage impossible by construction

## Files Changed

- `apps/api/src/auth.py` — add `_verify_token` helper + `get_current_org_id`
- `apps/api/src/routers/velocity.py` — new file
- `apps/api/src/main.py` — include velocity router
