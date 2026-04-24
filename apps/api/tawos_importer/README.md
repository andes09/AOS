# TAWOS → Omada Importer

One-shot ETL that loads the [TAWOS dataset](https://github.com/SOLAR-group/TAWOS)
(508k+ real Jira issues from 44 open-source projects) into Omada's Postgres
schema so every feature can be exercised against realistic data volume and
shapes.

**⚠️ Never run against the production database.** The CLI refuses any
`DATABASE_URL` whose hostname matches a pattern in
`tawos_importer/config.py :: PROD_HOSTNAME_PATTERNS`.

## Why this exists

Seeded dev data is homogeneous — same ticket title shape, same sprint length,
same dependency density. Real Jira data has:

- 500+ char titles with unicode and markdown
- Sprints that ended before they started (data entry errors)
- Developers who only appear as reporters, never assignees
- Tickets that stay unestimated forever
- Blocking chains that span 4+ tickets and cross sprints

The importer surfaces bugs that seed data hides.

## Pieces in this directory

| File | Purpose |
|---|---|
| `config.py` | Paths, MySQL creds, prod-DB safety guard, logger setup |
| `docker-compose.yml` | Local MySQL 8.0 on port 3307 (source of truth for TAWOS data) |
| `download.py` | Fetches the `tawos.sql.zip` dump from UCL RDR, idempotent |
| `load_mysql.py` | Sources the dump into the local MySQL container, idempotent |
| `source_db.py` | PyMySQL connection helper (DictCursor, utf8mb4) |
| `inspect.py` | Dumps tables / columns / sample rows — run before mapping |
| `tawos_queries.py` | All read-only SQL against TAWOS lives here |
| `mapper.py` | Pure TAWOS-dict → Omada-model functions (unit-testable) |
| `importer.py` | Per-project async transaction, batched inserts, derived fields |
| `run_import.py` | CLI: `--list / --project / --all-small / --all / --reset` |
| `verify.py` | Post-import sanity checks (read-only) |

## One-time setup

```bash
# 1. MySQL for the source data (runs on port 3307 so it won't collide
#    with any MySQL you already have at 3306).
cd apps/api/tawos_importer
docker compose up -d

# 2. PyMySQL is in api dev deps — install it:
cd ..                              # into apps/api
uv sync --extra dev

# 3. Download the TAWOS dump (~600MB zipped, ~2.5GB unzipped).
python -m tawos_importer.download

# 4. Source the dump into MySQL (first run takes 10–30 minutes).
python -m tawos_importer.load_mysql
```

If the UCL-hosted URL goes stale, override:
```bash
TAWOS_DUMP_URL=https://example.com/tawos.sql.zip python -m tawos_importer.download
```

## Inspect the source schema before writing new mappings

```bash
python -m tawos_importer.inspect                   # overview: tables + row counts, sample 5 rows from main tables
python -m tawos_importer.inspect --table Issue     # one table only
python -m tawos_importer.inspect --sample 0        # schema only, no rows
```

## Import projects

```bash
# List what's available and how big
python -m tawos_importer.run_import --list

# A single project (fastest way to smoke test)
python -m tawos_importer.run_import --project APACHE-KAFKA

# First 500 issues only (for quick local iteration)
python -m tawos_importer.run_import --project APACHE-KAFKA --limit-issues 500

# Every small project (<1,000 issues each) — good baseline for full test
python -m tawos_importer.run_import --all-small

# Everything — can take hours on the largest projects
python -m tawos_importer.run_import --all
```

Logs stream to stderr AND append to `apps/api/tawos_importer/import.log`.

## Verify

```bash
python -m tawos_importer.verify                               # every simulated team
python -m tawos_importer.verify --project-key APACHE-KAFKA    # one project
python -m tawos_importer.verify --team-id <uuid>              # one team
```

Exits 1 on any check failure.

## Reset simulated data

```bash
python -m tawos_importer.run_import --reset --confirm
```

Deletes every row in every organization where `is_simulated=TRUE`. The
`--confirm` flag is required so a typo can't wipe data. Real customer orgs
(`is_simulated=FALSE`, the default) are untouched.

## How TAWOS fields map to Omada

| TAWOS (source) | Omada (target) | Notes |
|---|---|---|
| `Project` | `Organization` + `Team` | org name prefixed `[TAWOS]`, `is_simulated=TRUE` |
| `User` | `Developer` + `TeamMember` | both rows created per user, linked by display_name |
| `Sprint` | `Sprint` | state `CLOSED→COMPLETED`, `FUTURE→PLANNING`, bad rows (end<start) skipped |
| `Issue` | `Ticket` | status normalized to TicketStatus enum; unknown → TODO |
| `Issue_Link` | `Dependency` | only `blocks` / `is blocked by` link types; risk classified from blocker resolution dates |

Per-ticket derived data:
- `Sprint.committed_points` = sum of ticket `story_points_estimated`
- `Sprint.delivered_points` = sum where `status = DONE`
- `SprintTicket` rows created for every (ticket, sprint, developer-assignee) triple so Velocity Mirror has historical signal

## Skipped in v1

To keep the first import simple, these TAWOS fields are not yet loaded:

- Comments and comment history
- Attachments, watchers, voters
- Custom fields (per-project bespoke Jira fields)
- Issue resolution types beyond Done / Not Done
- `Issue_Changelog` (status transition history) — `is_carryover` uses the
  `Sprint_Issue` join table if present, otherwise stays FALSE

## Known limitations

- **`Developer.baseline_velocity` is not populated as a scalar.** Omada's
  schema doesn't have that column; velocity is derived from `SprintTicket`
  rows. Sprint Brain / Velocity Mirror read from there, so this is working
  as intended, but a `Developer.baseline_velocity` shortcut column could
  be added in a future migration if the computation gets expensive.
- **`Ticket.description` is not imported.** The Omada ticket model doesn't
  currently have a description field. Add one in a migration if needed.
- **Sprint-issue history** depends on the `Sprint_Issue` table being
  present in your TAWOS dump. If it's absent, every ticket imports with
  `is_carryover=FALSE`. Run `inspect.py --table Sprint_Issue` to check.

## Troubleshooting

### `cannot reach tawos mysql at 127.0.0.1:3307`
The container isn't running. `docker compose up -d` from this directory.

### `mysql CLI not found on PATH`
`load_mysql.py` uses the mysql client binary. Install it:
```bash
brew install mysql-client
echo 'export PATH="/opt/homebrew/opt/mysql-client/bin:$PATH"' >> ~/.zshrc
```

### `Refusing to run TAWOS import against production DB`
Your `DATABASE_URL` matches a pattern in `PROD_HOSTNAME_PATTERNS`. Point at
staging or local instead. Edit `config.py` to add new production patterns as
your infra grows.

### Import crashes halfway through a single project
The transaction rolls back — the DB is left clean. Inspect the error, fix
the root cause (usually a TAWOS column-name variation — look at the mapper's
`_pick()` candidates), and re-run.

### `--all` finishes with failures
Every successful project is committed individually. Re-run `--all` — it
will re-create orgs for already-imported projects (new UUIDs), so first
`--reset --confirm` if you want a clean slate.

## Schema migration

The importer depends on Alembic revision `0015` which adds:
- `organizations.is_simulated BOOLEAN NOT NULL DEFAULT FALSE`
- `tickets.is_carryover BOOLEAN NOT NULL DEFAULT FALSE`

Run `alembic upgrade head` (or your deploy's migration runner) before the
first import.
