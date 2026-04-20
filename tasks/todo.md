# TAWOS Dataset Importer — Plan

Branch: `tawos-importer` (created ✅)

## Context gathered from reading models

Before writing the plan I read every Omada model under `apps/api/src/models/`.
The task spec's conceptual mapping is correct, but several field names and
relationships differ from what the spec describes. Those are flagged below so
we agree on the approach before any code is written.

## Schema mismatches vs. the task spec

| Spec says | Reality | How I'll handle |
|---|---|---|
| `Organization.is_simulated` column exists | Not in model | **Alembic migration 0015** adds `is_simulated BOOLEAN NOT NULL DEFAULT FALSE` — spec explicitly allows this |
| `Developer.display_name` | Field is `name` | Map `username` → `Developer.name` |
| `Developer.baseline_velocity` | Field doesn't exist | Compute avg delivered pts/sprint, store on `DeveloperVelocityProfile.mean_completion_days` + `sprint_count`; keep a helper to expose it |
| `Ticket.description` (truncate to 5000) | Field doesn't exist | Skip description entirely (title is Text and stores full title) |
| `Ticket.is_carryover` | Field doesn't exist | **Migration 0015** adds `is_carryover BOOLEAN NOT NULL DEFAULT FALSE` |
| `Ticket.story_points` | Field is `story_points_estimated` | Map accordingly |
| `Ticket.assignee_developer_id` | FK is `assignee_id → team_members.id` | Create BOTH `Developer` and `TeamMember` rows per TAWOS user; `Ticket.assignee_id` points at TeamMember |
| `Ticket.updated_at` | Field is `jira_updated_at` | Use that |
| `Sprint.status` has FUTURE | Enum: PLANNING/ACTIVE/COMPLETED/CANCELLED | Map `FUTURE→PLANNING`, `ACTIVE→ACTIVE`, `CLOSED→COMPLETED` |
| `Dependency.blocking_ticket_id`/`blocked_ticket_id` | Actual: `ticket_key` (blocked) + `blocked_by_key` (blocker) + `team_id` + `dependency_type` + `risk_level` + `source` | Map to actual column names |

## Implementation plan (5 commits matching spec's commit structure)

### Commit 1 — download & inspect tooling
- [ ] Create `apps/api/tawos_importer/` with `__init__.py`, `data/` gitignore
- [ ] `download.py`: download TAWOS SQLite from https://github.com/SOLAR-group/TAWOS, idempotent (skip if file exists with correct size)
- [ ] `inspect.py`: print all tables, row counts, sample 5 rows per main table, full column list
- [ ] Add `.gitignore` entry for `apps/api/tawos_importer/data/`

### Commit 2 — schema mapper
- [ ] **Migration 0015**: add `organizations.is_simulated`, `tickets.is_carryover`
- [ ] `mapper.py`:
  - `map_project(tawos_project) → (Organization, Team)`
  - `map_user(tawos_user) → (Developer, TeamMember)`
  - `map_sprint(tawos_sprint) → Sprint`
  - `map_issue(tawos_issue, sprint_lookup, team_member_lookup) → Ticket`
  - `map_link(tawos_link, ticket_lookup) → Dependency | None` (only blocks/is_blocked_by)
  - All mapping functions are **pure** (dict in, SQLA model out) — easy to unit test
  - Handle edge cases: null assignee, null points, unicode, truncation, etc.

### Commit 3 — project import logic with transaction handling
- [ ] `importer.py`:
  - `async def import_project(project_id, session, limit_issues=None)`
  - Single async DB transaction per project (rollback on any failure)
  - Order: Org → Team → Developers (+ TeamMembers) → Sprints → Tickets (batched 500) → Dependencies
  - Compute derived fields:
    - `Sprint.committed_points` = sum of tickets at sprint start
    - `Sprint.delivered_points` = sum of tickets moved to Done before sprint close
    - `DeveloperVelocityProfile` per developer (baseline velocity)
  - Structured logging: `[tawos] Imported <name>: N devs, M sprints, K tickets, L deps`

### Commit 4 — CLI interface + edge cases
- [ ] `run_import.py` CLI with flags: `--list`, `--project`, `--limit-issues`, `--all-small`, `--all`, `--reset --confirm`
- [ ] Log to `apps/api/tawos_importer/import.log` with timestamps
- [ ] `--reset` guarded by `--confirm` and deletes only `is_simulated=TRUE` orgs (never production data)
- [ ] Verification script `verify.py` for post-import sanity checks (orphan rows, point sums, velocity > 0)

### Commit 5 — README + docs
- [ ] `apps/api/tawos_importer/README.md`: download, inspect, import, reset, troubleshooting, known limitations
- [ ] Note the skipped fields (comments, attachments, watchers, custom fields, resolution types)

## Safety guardrails

- Spec explicitly out of scope: modifying Omada model schemas beyond `is_simulated` + `is_carryover`, running against production. I will NOT run migrations or imports against prod Railway DB — local Postgres only.
- `is_simulated` migration is additive-only (nullable/defaulted), cannot break existing data.
- Every CLI entry point confirms the target DB URL before proceeding when it looks like a production host (hostname contains `railway`, `prod`, etc.).

## Open questions for user (before I start coding)

1. **Is adding migration 0015 (`is_simulated`, `is_carryover`) OK?** Spec implies yes but `is_carryover` isn't explicitly pre-approved — it's needed for the "carryover" mapping rule in the spec. Alternative: derive carryover on-read (no migration needed) by joining sprint_tickets history.
2. **TAWOS issue → Ticket.assignee_id** points to `team_members`, not `developers`. Confirm: create both a `Developer` (for velocity/app users) and `TeamMember` (for ticket assignment) row per TAWOS username, linked by display_name? This matches how Jira-imported data works today.
3. **Where should imports run?** `apps/api/.env` database URL — I'll read from there. Confirm this points to your local Docker Postgres (not Railway).

If the answers are (1) yes to migration, (2) yes dual-row, (3) local only — I'll proceed. Otherwise, I'll revise.

## Review section (fill in after implementation)

_Pending implementation._
