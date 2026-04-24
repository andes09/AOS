# TAWOS Importer — Known Limitations

These are *limitations*, not bugs — features intentionally deferred to a later
revision. Each entry records the shape of the gap so future work can close it
without re-discovering the constraint.

## `is_carryover` is always `FALSE`

Every ticket imported by v1 has `is_carryover=FALSE`, regardless of whether the
underlying Jira ticket actually slipped between sprints.

### Why

The shipped TAWOS dump does not include a `Sprint_Issue` join table. The
importer already tries to read it (see `tawos_queries.py::fetch_issue_sprint_history`)
and falls back to an empty mapping when the table is absent — which is the case
for the current UCL-hosted dump.

### How to fix (future work)

TAWOS ships an `Issue_Changelog` / `Change_Log` table containing per-field
status/sprint transitions. A carryover derivation would:

1. For each ticket, pull changelog rows where `Field_Name = 'Sprint'`.
2. Walk them chronologically; if a ticket is moved from an active/closed
   sprint to another sprint, mark `is_carryover=TRUE` on its current sprint
   assignment.
3. Run this as a second pass after tickets are persisted so it doesn't slow
   the hot ingest path.

Until that work lands, dashboards that segment by carryover will treat every
TAWOS ticket as net-new in its current sprint.

## `Developer.baseline_velocity` is not a scalar column

Omada's schema derives velocity from `sprint_tickets.completed` rather than
storing a per-developer scalar. This is working as intended; documenting here
because the spec implied a column. Future optimization: cache a scalar on
`developers` if the live query becomes a hot-path.

## `Ticket.description` is not imported

The Omada `tickets` table has no description column. TAWOS's `Description` and
`Description_Text` fields are dropped on import. Adding a migration + column is
straightforward if a later feature needs it.

## TAWOS blockers are typically backlog tickets without sprints

### Observation

In every project we've sampled (MESOS, CLI, DAEMON), the tickets that *block*
other work overwhelmingly do NOT have `Sprint_ID` populated. They are
long-lived backlog items — architectural work, parent epics, external
dependencies — that were never scheduled into a sprint. The tickets they
block, by contrast, often are sprint-scheduled.

This matters for dependency risk classification. The sprint-based HIGH rule
("blocker has slipped past its own sprint end") cannot fire if the blocker
has no sprint in the first place. Absent the staleness branch below, this
collapses almost every imported dependency to `risk_level=medium`.

### How the importer handles it

`mapper.py :: map_link_risk` has two independent HIGH triggers:
1. **Sprint-based** — original: blocker unresolved past its sprint end.
2. **Staleness-based** — blocker is not `DONE` AND was created more than
   `STALE_BLOCKER_AGE_DAYS` (currently 60) before the blocked ticket's
   `sprint_start` (or before `date.today()` if the blocked ticket has no
   sprint either).

The staleness rule catches stale-backlog blockers that the sprint rule
misses — which, for TAWOS, is the majority of them.

### Expectation for real customer data

Customer Jira projects where both sides of a `blocks` relationship are
actively being worked on (both in sprints) will route through the
sprint-based rule and should produce a more natural LOW / MEDIUM / HIGH
spread. TAWOS's heavy medium/high skew is a property of the public Jira
data, not a general ceiling.

## Anonymized usernames

The shipped TAWOS `User` table has only `(ID, Project_ID)` — no `Username` or
`Full_Name`. The importer synthesizes `user_<ID>` as the handle so every
assignee remains distinct and stable. `Developer.name`, `TeamMember.display_name`,
and generated emails all flow from this synthesized handle. UI that shows
assignee names will show `user_1234` rather than real names for TAWOS data.
