# AOS Phase 2 — Contract & Implementation Specifications

**This is the primary agent reference for Phase 2.** Each section defines exactly what to build — DB schema, API shape, service logic, frontend. Read your assigned contract in full before writing any code. After completing, cross-check with `docs/plans/aos-phase2-checklist.md` to confirm every item is checked.

Phase 1 contracts live in `docs/plans/aos-contracts.md`. Migration numbers continue from `0010`. Track numbers continue from `25`.

---

## How to Use This Document

1. **Identify your contract** from the wave execution plan below
2. **Read the full contract section** — goal, pre-conditions, schema, API, service logic, frontend, verification
3. **Check current state before writing** — many files already exist and must be edited in place, not re-created
4. **Build bottom-up within your contract** — DB first, service second, router third, frontend last
5. **Verify before marking complete** — verification steps are mandatory

---

## Universal Conventions

### File paths
| Layer | Path pattern |
|---|---|
| API models | `apps/api/src/models/{name}.py` |
| API services | `apps/api/src/services/{name}.py` |
| API routers | `apps/api/src/routers/{name}.py` |
| Migrations | `apps/api/alembic/versions/{n}_{description}.py` |
| Jira client extensions | `apps/api/src/integrations/jira/client.py` |
| Calendar integrations | `apps/api/src/integrations/{provider}_calendar/` |
| Frontend pages | `apps/web/src/pages/{Name}Page.tsx` |
| Frontend components | `apps/web/src/components/{group}/{Name}.tsx` |
| Frontend types | `apps/web/src/types/{name}.ts` |
| Frontend hooks | `apps/web/src/hooks/use{Name}.ts` |
| Frontend contexts | `apps/web/src/contexts/{Name}Context.tsx` |

### Naming conventions
| Layer | Convention | Example |
|---|---|---|
| DB columns | `snake_case` | `meeting_overhead_pct`, `team_id` |
| Python variables | `snake_case` | `meeting_overhead_pct` |
| API JSON fields | `camelCase` via `alias_generator=to_camel` | `meetingOverheadPct`, `teamId` |
| URL paths | `kebab-case` | `/api/capacity-settings/team/{team_id}` |
| Frontend variables | `camelCase` | `meetingOverheadPct`, `teamId` |

### Response model pattern — required on every new Pydantic response model
```python
model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
```
Python field `team_id: str` → JSON `"teamId"`. Never manually alias fields — use the config.

### Enum storage rule — critical, enforced across all contracts
- **Existing enums** (`SprintStatus`, `TicketStatus`): PostgreSQL native enums, UPPERCASE values. Do not touch.
- **All new enums**: `native_enum=False` + `values_callable=lambda obj: [e.value for e in obj]`. Stored as lowercase VARCHAR. No PostgreSQL type created. No rename risk.

### Migration conventions
- File naming: `0011_...`, `0012_...` — continue from `0010_add_tickets_components.py`
- Every migration must be fully idempotent: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `ADD CONSTRAINT IF NOT EXISTS`
- Apply with: `python migrate.py`
- Run `python migrate.py` on a fresh DB after every Wave 1 pass. It must apply cleanly with zero errors.

### Role hierarchy (unchanged from Phase 1)
```
developer(0) < lead(1) < exec(2) < admin(3)
```
Enforced by `require_role(minimum)` from `src/auth_roles.py`. Import and use this dependency on every protected endpoint. Never inline role checks.

### Claude client pattern (unchanged from Phase 1)
All Claude API calls use `get_anthropic_key(clerk_org_id, db)` from `src/services/ai_client.py`. Never inline key fetching.

### `'default'` team_id sentinel
All endpoints that accept `team_id` as a path or query parameter must handle the `'default'` sentinel by resolving it to the org's first team via `clerk_org_id`. Do not let `uuid.UUID('default')` propagate — it raises `ValueError` which is caught by some routers as unexpected errors.

### Shell state rule (this machine)
Shell state does not persist between separate Bash tool calls. Always chain git operations with `&&` in a single command.

### Shared files — single-agent cleanup rule
These files are touched by multiple contracts. Do not have multiple agents edit them in parallel:
- `apps/api/src/main.py` — one agent does all router registrations per wave
- `apps/web/src/App.tsx` — one agent adds all new routes per wave
- `apps/web/src/layouts/DashboardLayout.tsx` — one agent adds TeamSwitcher and nav links (Track 39)
- `apps/web/src/pages/SprintPlannerPage.tsx` — touched by Track 32; read current state before editing
- `apps/web/src/pages/SettingsPage.tsx` — touched by Track 40; read current state before editing

---

## Wave Execution Plan

| Wave | Purpose | Tracks |
|---|---|---|
| **0** | Lock all contracts — no code written | Track 25 (this document) |
| **1** | DB only — migrations 0011–0014 applied and verified | Tracks 25-DB, 30-DB, 36-DB (0011, 0012, 0014) |
| **2** | Internal logic — service files only, no router changes | Tracks 26, 27-svc, 31-svc, 37-svc, 38-svc |
| **3** | API endpoints — all routers written and registered in `main.py` | Tracks 28, 27-router, 31-router, 37-router, 38-router |
| **4** | Frontend — all pages and components | Tracks 29, 32, 39, 40 |
| **P2 Deferred** | Calendar integrations | Tracks 33 (DB), 34 (Google), 35 (Microsoft) |

### Wave gates
- **Wave 0:** Every contract item in Track 25 of the checklist is checked
- **Wave 1:** `python migrate.py` applies 0011–0014 cleanly on a fresh DB; all new tables visible in `information_schema.tables`
- **Wave 2:** Each service function verifiable in isolation (mock DB); capacity math correct against known inputs
- **Wave 3:** `GET /docs` loads without import errors; all new endpoints in OpenAPI spec; role guards return 403 for insufficient role
- **Wave 4:** All new pages load without console errors; wizard flow completes; team switcher changes team context; Slack config saves and test message sends
- **P2 Deferred:** Calendar integrations only start after Wave 4 gate passes; they must not block any Wave 1–4 track

---

## Contract K — Onboarding

**Goal:** Replace the current bare-bones onboarding flow with a guided setup wizard. New teams complete four steps in sequence: (1) connect Jira, (2) select board, (3) import sprint history, (4) invite team members. Meaningful empty states on each dashboard explain what data is needed and when AI features unlock. Email or shareable-link invitations bring team members in without requiring them to navigate directly.

**Tracks:** 25 (DB), 26 (services), 27 (invitation service + API), 28 (onboarding API), 29 (frontend)
**Waves:** 1 (DB), 2 (services), 3 (routers + `main.py`), 4 (frontend)
**Depends on:** Existing `OnboardingPage.tsx`, existing Jira OAuth flow, existing `JiraConnection` model

**Current state:** `OnboardingPage.tsx` exists but shows a single Jira connect screen with no step progression. No `invitations` table. No mechanism to track which onboarding steps are complete. No empty-state components on dashboards.

### DB Schema — Wave 1 (Track 25)

**Column additions** — edit `apps/api/src/models/organization.py` in place:
```python
onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

**Column additions** — edit `apps/api/src/models/team.py` in place:
```python
jira_import_status: Mapped[str] = mapped_column(
    String(20), nullable=False, server_default="pending"
)
# Values: "pending" | "in_progress" | "completed" | "failed"
jira_import_sprints_imported: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

**New table** — new file `apps/api/src/models/invitation.py`:
```python
class InvitationStatus(enum.Enum):
    PENDING  = "pending"
    ACCEPTED = "accepted"
    REVOKED  = "revoked"
    EXPIRED  = "expired"

class Invitation(Base):
    __tablename__ = "invitations"

    id:              Mapped[uuid.UUID]       # PK
    organization_id: Mapped[uuid.UUID]       # FK organizations.id, NOT NULL
    team_id:         Mapped[uuid.UUID]       # FK teams.id, NOT NULL
    inviter_id:      Mapped[str]             # Clerk user id, NOT NULL
    email:           Mapped[str]             # VARCHAR(255), NOT NULL
    role:            Mapped[str]             # VARCHAR(20) DEFAULT 'developer'
    token:           Mapped[str]             # VARCHAR(64) UNIQUE NOT NULL
    status:          Mapped[str]             # VARCHAR(20) DEFAULT 'pending'
    accepted_at:     Mapped[datetime | None] # TIMESTAMP NULL
    expires_at:      Mapped[datetime]        # TIMESTAMP NOT NULL
    created_at:      Mapped[datetime]        # TIMESTAMP DEFAULT now()
```
`role` and `status` use `native_enum=False`. Export `Invitation`, `InvitationStatus` from `models/__init__.py`.

**New migration** `apps/api/alembic/versions/0011_onboarding_and_invitations.py`:
```sql
-- up
ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMP;

ALTER TABLE teams
    ADD COLUMN IF NOT EXISTS jira_import_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS jira_import_sprints_imported INTEGER;

CREATE TABLE IF NOT EXISTS invitations (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    team_id         UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    inviter_id      VARCHAR(255) NOT NULL,
    email           VARCHAR(255) NOT NULL,
    role            VARCHAR(20)  NOT NULL DEFAULT 'developer',
    token           VARCHAR(64)  NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    accepted_at     TIMESTAMP,
    expires_at      TIMESTAMP    NOT NULL,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_invitation_token ON invitations(token);
CREATE INDEX IF NOT EXISTS ix_invitations_org_id     ON invitations(organization_id);
CREATE INDEX IF NOT EXISTS ix_invitations_email      ON invitations(email);

-- down
DROP TABLE IF EXISTS invitations;
ALTER TABLE teams DROP COLUMN IF EXISTS jira_import_sprints_imported;
ALTER TABLE teams DROP COLUMN IF EXISTS jira_import_status;
ALTER TABLE organizations DROP COLUMN IF EXISTS onboarding_completed_at;
```

### Service Logic — Wave 2 (Track 26)

**New file** `apps/api/src/services/onboarding.py`:

```python
async def get_onboarding_status(org_id: uuid.UUID, db: AsyncSession) -> dict:
    """
    Returns a dict with five boolean/string fields:
      jiraConnected:         True if an active JiraConnection exists for org
      boardSelected:         True if team.jira_board_id is set
      importStatus:          team.jira_import_status ("pending"|"in_progress"|"completed"|"failed")
      importedSprints:       team.jira_import_sprints_imported (int or None)
      onboardingCompleted:   True if org.onboarding_completed_at is not None
    """

async def import_jira_sprint_history(
    team: Team,
    jira_client: JiraClient,
    sprint_count: int,
    db: AsyncSession,
) -> int:
    """
    Fetches the last `sprint_count` completed sprints from Jira for the team's board.
    For each sprint: upserts a Sprint row (COMPLETED status) with committed_points
    and delivered_points derived from Jira sprint report data.
    Also imports tickets belonging to those sprints (upsert on jira_issue_id).
    Returns the count of sprints imported.
    Sets team.jira_import_status = "completed" and team.jira_import_sprints_imported = count.
    On any JiraClient error, sets jira_import_status = "failed" and re-raises.
    """
```

**New file** `apps/api/src/services/invitation.py`:

```python
import secrets
from datetime import datetime, timedelta

async def create_invitation(
    organization_id: uuid.UUID,
    team_id: uuid.UUID,
    inviter_id: str,
    email: str,
    role: str,
    db: AsyncSession,
) -> Invitation:
    """
    Creates an Invitation with:
      token = secrets.token_urlsafe(32)
      expires_at = utcnow() + 7 days
      status = "pending"
    Idempotent on (organization_id, email): if a pending invitation already
    exists for this email, return the existing one without creating a duplicate.
    """

async def accept_invitation(token: str, clerk_user_id: str, db: AsyncSession) -> Invitation:
    """
    Validates token (exists, status=pending, not expired).
    Sets invitation.status = "accepted", accepted_at = utcnow().
    Upserts a Developer row for the accepting user in the invitation's team
    with the invitation's role.
    Returns the updated Invitation.
    Raises HTTPException(404) if token not found.
    Raises HTTPException(410) if expired or already accepted/revoked.
    """

def build_invite_link(token: str, frontend_base_url: str) -> str:
    """Returns f"{frontend_base_url}/invite?token={token}"."""
```

### API Spec — Wave 3 (Track 28)

**New file** `apps/api/src/routers/onboarding.py`.
Register in `main.py`:
- `app.include_router(onboarding_router, prefix="/api/onboarding")`
- `app.include_router(invitations_router, prefix="/api/invitations")`

#### `GET /api/onboarding/status`
```
Auth: any authenticated user
Response 200:
{
  "jiraConnected":       boolean,
  "boardSelected":       boolean,
  "importStatus":        "pending" | "in_progress" | "completed" | "failed",
  "importedSprints":     number | null,
  "onboardingCompleted": boolean
}
```

#### `POST /api/onboarding/complete`
```
Auth: any authenticated user
Request: {} (empty body)
Response 200: { "completedAt": string (ISO-8601) }
Side effect: sets org.onboarding_completed_at = utcnow()
```

#### `POST /api/onboarding/import-history`
```
Auth: any authenticated user
Request: { "sprintCount": number }  (1–6; default 3 if omitted; clamped to range)
Response 202: { "status": "in_progress", "sprintCount": number }
Side effect: sets team.jira_import_status = "in_progress" immediately;
             calls import_jira_sprint_history() inline (no Celery); updates status on completion
Response 402: no active Jira connection
Response 422: board not selected yet
```

#### `GET /api/onboarding/import-status`
```
Auth: any authenticated user
Response 200: { "status": string, "importedSprints": number | null }
```

#### `POST /api/invitations`
```
Auth: require_role("lead")
Request: { "email": string, "role": "developer" | "lead" }
Response 201:
{
  "id":        string,
  "email":     string,
  "role":      string,
  "inviteLink": string,   ← full URL: {FRONTEND_URL}/invite?token={token}
  "expiresAt": string,
  "status":    "pending"
}
Response 409: pending invitation already exists for this email (return existing)
```

#### `GET /api/invitations`
```
Auth: require_role("lead")
Response 200: { "invitations": [InvitationItem] }
InvitationItem: { id, email, role, status, inviteLink, expiresAt, createdAt }
```

#### `DELETE /api/invitations/{invitation_id}`
```
Auth: require_role("lead")
Response 200: { "revoked": true }
Side effect: sets invitation.status = "revoked"
Response 404: not found
```

#### `POST /api/invitations/accept`
```
Auth: any authenticated user (token is the credential)
Request: { "token": string }
Response 200: { "teamId": string, "role": string, "acceptedAt": string }
Response 404: token not found
Response 410: token expired or already accepted/revoked
```

All response models use `ConfigDict(alias_generator=to_camel, populate_by_name=True)`.

### Frontend Spec — Wave 4 (Track 29)

**Edit** `apps/web/src/pages/OnboardingPage.tsx` — replace single-screen with a 4-step wizard:
- Step 1: Connect Jira (existing OAuth flow, detect completion from `GET /api/onboarding/status`)
- Step 2: Select Board (existing board selector, detect `boardSelected` from status)
- Step 3: Import History — show "Import last N sprints" selector (1–6) with "Import Now" button calling `POST /api/onboarding/import-history`; poll `GET /api/onboarding/import-status` every 3s until status is `completed` or `failed`; show progress indicator
- Step 4: Invite Team — email input + role selector calling `POST /api/invitations`; shows shareable link; "Skip for now" option; "Done" calls `POST /api/onboarding/complete` then navigates to `/app/sprint-planner`

Step indicator bar at top showing current step (1–4) and completion status.

**New file** `apps/web/src/pages/InviteAcceptPage.tsx`:
- Reads `?token=` from URL
- Calls `POST /api/invitations/accept` with the token on mount
- Success: shows "You've joined {team name} as {role}" + "Go to Dashboard" button
- Error 404/410: explains token is invalid or expired

**New file** `apps/web/src/components/onboarding/EmptyStateCard.tsx`:
```tsx
interface EmptyStateCardProps {
  icon: string           // emoji or icon name
  title: string
  description: string
  sprints_needed?: number // "AI unlocks after N more sprints"
  action?: { label: string; onClick: () => void }
}
```
Used on: `SprintPlannerPage` (no plan yet), `VelocityMirrorPage` (no sprint data), `RetrospectivePage` (no retro), `DependencyRadarPage` (no scan yet).

**New file** `apps/web/src/types/onboarding.ts`:
```typescript
interface OnboardingStatus {
  jiraConnected: boolean
  boardSelected: boolean
  importStatus: 'pending' | 'in_progress' | 'completed' | 'failed'
  importedSprints: number | null
  onboardingCompleted: boolean
}

interface InvitationItem {
  id: string
  email: string
  role: string
  status: string
  inviteLink: string
  expiresAt: string
  createdAt: string
}
```

**Add route** in `App.tsx`:
```tsx
<Route path="/invite" element={<InviteAcceptPage />} />
```
(This route is outside the `/app` guard — no auth required; invitation token is the credential.)

### Verification
- `python migrate.py` applies `0011` cleanly; insert duplicate token → `UniqueViolation`
- `GET /api/onboarding/status` returns correct `jiraConnected: false` before Jira setup
- `POST /api/onboarding/import-history` with `sprintCount: 3` and active Jira connection → imports sprints; `GET /api/sprint-brain/plan` now succeeds without seed data
- `POST /api/invitations` → returns invite link; following link as different user → accepts; developer row created with correct role
- Expired token (`expires_at` in past) → `POST /api/invitations/accept` returns 410
- Already-accepted token → 410

---

## Contract L — Meeting Overhead & Capacity

**Goal:** Let leads configure how much meeting time reduces each developer's effective sprint capacity. Two layers: (1) a flat team-wide meeting overhead percentage that Sprint Brain deducts from all developer capacities automatically, (2) per-developer, per-sprint capacity overrides with optional notes for one-off situations (PTO, partial week, etc.). Sprint Brain's plan response and capacity summary must reflect these deductions. Flag developers whose effective capacity has dropped below 60% of their baseline due to meeting load.

Google Calendar and Microsoft Teams/Outlook calendar integrations are included here as P2 — full contracts are specified but their wave tracks are deferred until Phase 2 P2 execution.

**Tracks:** 30 (DB), 31 (service + API), 32 (frontend), 33 (P2 DB — calendar_connections), 34 (P2 Google Calendar), 35 (P2 Microsoft Calendar)
**Waves:** 1 (DB), 2 (service), 3 (router), 4 (frontend)
**Depends on:** Existing `Developer`, `Team`, `Sprint` models; existing `SprintBrainInput` in `services/sprint_brain.py`

**Current state:** No `meeting_overhead_pct` on teams. No `developer_capacity_overrides` table. `SprintBrainInput` has a `pto_overrides: dict[str, float]` field but no meeting-aware capacity model. No capacity settings UI.

### DB Schema — Wave 1 (Track 30)

**Column addition** — edit `apps/api/src/models/team.py` in place:
```python
meeting_overhead_pct: Mapped[float] = mapped_column(
    Float, nullable=False, server_default="0.0"
)
# 0.0–1.0 fraction. e.g. 0.20 = 20% of sprint hours consumed by meetings.
```

**New table** — new file `apps/api/src/models/capacity.py`:
```python
class DeveloperCapacityOverride(Base):
    __tablename__ = "developer_capacity_overrides"

    id:           Mapped[uuid.UUID]       # PK
    developer_id: Mapped[uuid.UUID]       # FK developers.id, NOT NULL
    sprint_id:    Mapped[uuid.UUID | None] # FK sprints.id, NULL = applies to next sprint
    capacity_pct: Mapped[float | None]    # 0.0–1.0 override (replaces baseline)
    pto_days:     Mapped[float | None]    # days off this sprint
    notes:        Mapped[str | None]      # TEXT
    created_by:   Mapped[str]             # Clerk user id
    created_at:   Mapped[datetime]        # TIMESTAMP DEFAULT now()
```
Unique constraint on `(developer_id, sprint_id)` — one override per developer per sprint. `sprint_id` NULL means "applies to the next unstarted sprint for this team".

Export `DeveloperCapacityOverride` from `models/__init__.py`.

**New migration** `apps/api/alembic/versions/0012_meeting_overhead_and_capacity.py`:
```sql
-- up
ALTER TABLE teams
    ADD COLUMN IF NOT EXISTS meeting_overhead_pct FLOAT NOT NULL DEFAULT 0.0;

CREATE TABLE IF NOT EXISTS developer_capacity_overrides (
    id           UUID PRIMARY KEY,
    developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    sprint_id    UUID REFERENCES sprints(id) ON DELETE CASCADE,
    capacity_pct FLOAT,
    pto_days     FLOAT,
    notes        TEXT,
    created_by   VARCHAR(255) NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dev_capacity_sprint
    ON developer_capacity_overrides(developer_id, sprint_id)
    WHERE sprint_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_dev_capacity_dev_id
    ON developer_capacity_overrides(developer_id);

-- down
DROP TABLE IF EXISTS developer_capacity_overrides;
ALTER TABLE teams DROP COLUMN IF EXISTS meeting_overhead_pct;
```

### P2 DB — Wave P2 Only (Track 33)

**New table** — new file `apps/api/src/models/calendar_connection.py`:
```python
class CalendarProvider(enum.Enum):
    GOOGLE    = "google"
    MICROSOFT = "microsoft"

class CalendarConnection(Base):
    __tablename__ = "calendar_connections"

    id:                    Mapped[uuid.UUID]
    organization_id:       Mapped[uuid.UUID]       # FK organizations.id
    provider:              Mapped[str]              # VARCHAR(20) native_enum=False
    encrypted_access_token:  Mapped[str]
    encrypted_refresh_token: Mapped[str | None]
    token_expires_at:      Mapped[datetime | None]
    scopes:                Mapped[list | None]      # JSONB
    is_active:             Mapped[bool]             # DEFAULT TRUE
    created_at:            Mapped[datetime]
```
`provider` uses `native_enum=False`. Unique constraint on `(organization_id, provider)` — one connection per provider per org.

**New migration** `apps/api/alembic/versions/0013_calendar_connections.py`:
```sql
-- up
CREATE TABLE IF NOT EXISTS calendar_connections (
    id                      UUID PRIMARY KEY,
    organization_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider                VARCHAR(20) NOT NULL,
    encrypted_access_token  TEXT NOT NULL,
    encrypted_refresh_token TEXT,
    token_expires_at        TIMESTAMP,
    scopes                  JSONB,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_calendar_conn_org_provider
    ON calendar_connections(organization_id, provider)
    WHERE is_active = TRUE;
-- down
DROP TABLE IF EXISTS calendar_connections;
```

### Service Logic — Wave 2 (Track 31)

**New file** `apps/api/src/services/capacity.py`:

```python
from dataclasses import dataclass

SPRINT_WORKING_DAYS = 10      # default 2-week sprint
HOURS_PER_DAY = 7.5

@dataclass
class DeveloperEffectiveCapacity:
    developer_id: str
    display_name: str
    base_velocity: float          # avg points from historical sprints
    meeting_overhead_pct: float   # from team setting (0.0–1.0)
    pto_days: float               # from capacity override
    capacity_pct: float           # from capacity override (1.0 if none)
    effective_capacity_pts: float # base_velocity * capacity_pct * (1 - meeting_overhead_pct) - pto_adjustment
    is_high_meeting_load: bool    # True when effective_capacity < base_velocity * 0.60
    warning_message: str | None   # "Alex has {hours}h of meetings — effective capacity reduced to {pct}%"

async def get_team_capacity(
    team_id: str,
    sprint_id: str | None,
    db: AsyncSession,
) -> list[DeveloperEffectiveCapacity]:
    """
    For each active developer on the team:
    1. Load base_velocity from completed sprint history (avg delivered_points / active_devs)
    2. Load team.meeting_overhead_pct
    3. Load DeveloperCapacityOverride for (developer_id, sprint_id) if exists
    4. Compute effective_capacity_pts
    5. Set is_high_meeting_load if effective < base * 0.60
    Returns list sorted by display_name.
    """
```

**Edit** `apps/api/src/services/sprint_brain.py` — update `_get_developer_profiles()`:
After computing `per_dev_velocity`, load team's `meeting_overhead_pct` and any active capacity overrides. Adjust `safe_capacity_pts` field: multiply by `(1 - meeting_overhead_pct)` and apply any `capacity_pct` override. Add `meetingOverheadPct` and `capacityOverridePct` fields to the returned developer profile dict.

### API Spec — Wave 3 (Track 31, finish)

**New file** `apps/api/src/routers/capacity.py`.
Register in `main.py`: `app.include_router(capacity_router, prefix="/api/capacity")`

#### `GET /api/capacity/team/{team_id}`
```
Auth: require_role("lead")
Accepts team_id as UUID or "default"
Response 200:
{
  "teamId": string,
  "meetingOverheadPct": number,       ← team-wide setting (0.0–1.0)
  "developers": [DeveloperCapacityItem]
}
DeveloperCapacityItem:
{
  "developerId":          string,
  "displayName":          string,
  "baseVelocity":         number,
  "effectiveCapacityPts": number,
  "meetingOverheadPct":   number,     ← effective (team default, not overridden per-dev)
  "ptoDays":              number,
  "capacityPct":          number,
  "isHighMeetingLoad":    boolean,
  "warningMessage":       string | null
}
```

#### `PATCH /api/capacity/team/{team_id}/overhead`
```
Auth: require_role("lead")
Request: { "meetingOverheadPct": number }  (0.0–1.0; 422 if outside range)
Response 200: { "teamId": string, "meetingOverheadPct": number }
Side effect: updates team.meeting_overhead_pct
```

#### `PUT /api/capacity/team/{team_id}/developers/{developer_id}/override`
```
Auth: require_role("lead")
Request:
{
  "sprintId":   string | null,  ← null = applies to next sprint
  "capacityPct": number | null, ← 0.0–1.0
  "ptoDays":    number | null,
  "notes":      string | null
}
Response 200: DeveloperCapacityItem (re-computed after override applied)
Response 404: developer or sprint not found
Response 422: capacityPct outside 0.0–1.0
```

#### `DELETE /api/capacity/team/{team_id}/developers/{developer_id}/override`
```
Auth: require_role("lead")
Query param: sprint_id (optional; if omitted, deletes override with sprint_id IS NULL)
Response 200: { "deleted": true }
Response 404: no override found
```

### P2 API Spec — Google Calendar (Track 34)

**New file** `apps/api/src/integrations/google_calendar/oauth.py` — mirrors Jira OAuth pattern.
**New file** `apps/api/src/integrations/google_calendar/client.py` — `GoogleCalendarClient`:
```python
async def get_events(start: datetime, end: datetime) -> list[dict]:
    """Calls Google Calendar API v3 /events with timeMin/timeMax bounds.
    Returns events with start, end, summary, recurringEventId fields."""
```

**New router** `apps/api/src/routers/google_calendar.py`:

#### `GET /api/integrations/google-calendar/connect`
Returns `{ authUrl: string }`. Stores state token in-process dict (same pattern as Jira OAuth).

#### `GET /api/integrations/google-calendar/callback`
Exchanges code for tokens. Upserts `CalendarConnection` with `provider='google'`. Redirects to `{FRONTEND_URL}/settings?calendar=google_connected`.

#### `GET /api/integrations/google-calendar/status`
```
Response 200: { "connected": boolean, "lastSyncedAt": string | null }
```

#### `DELETE /api/integrations/google-calendar/disconnect`
Deactivates the CalendarConnection.

#### `GET /api/integrations/calendar/meetings/{team_id}`
```
Auth: require_role("lead")
Query params: start_date (YYYY-MM-DD), end_date (YYYY-MM-DD)
Response 200:
{
  "teamId": string,
  "developers": [{
    "developerId": string,
    "displayName": string,
    "totalMeetingHours": number,
    "recurringHours": number,
    "oneOffHours": number,
    "effectiveCapacityPct": number
  }]
}
Note: this endpoint only works if a CalendarConnection (google or microsoft) exists for the org.
Response 402: no calendar connected
```

**Service logic** — `apps/api/src/services/calendar_capacity.py`:
```python
async def compute_meeting_hours_from_calendar(
    org_id: uuid.UUID,
    developer_emails: list[str],
    sprint_start: date,
    sprint_end: date,
    db: AsyncSession,
) -> dict[str, float]:
    """
    Fetches CalendarConnection for org. For each developer email, fetches events
    in [sprint_start, sprint_end]. Sums event durations. Returns {email: total_hours}.
    Updates DeveloperCapacityOverride.meeting_hours for each developer.
    """
```

### P2 API Spec — Microsoft Calendar (Track 35)

Identical structure to Google Calendar. Uses Microsoft Graph API Calendar endpoint.

**New file** `apps/api/src/integrations/microsoft_calendar/oauth.py` — Microsoft OAuth 2.0 (MSAL flow).
**New file** `apps/api/src/integrations/microsoft_calendar/client.py` — `MicrosoftCalendarClient`:
```python
async def get_events(start: datetime, end: datetime) -> list[dict]:
    """Calls Microsoft Graph /me/calendarView with startDateTime/endDateTime.
    Returns events with subject, start, end, isRecurring fields."""
```

**New router** `apps/api/src/routers/microsoft_calendar.py`:
Same four endpoints as Google Calendar at prefix `/api/integrations/microsoft-calendar`. Both calendar integrations feed into the shared `GET /api/integrations/calendar/meetings/{team_id}` endpoint — provider is resolved from whichever `CalendarConnection` is active.

### Frontend Spec — Wave 4 (Track 32)

**New file** `apps/web/src/components/sprint/CapacitySettingsPanel.tsx`:
- Fetches `GET /api/capacity/team/default`
- Shows meeting overhead % slider (0–50%, maps to 0.0–0.5) with `PATCH /api/capacity/team/{id}/overhead` on change
- Shows per-developer table: developer name, base velocity, PTO days input, capacity % input, effective capacity pts
- Save button per row calls `PUT /api/capacity/team/{id}/developers/{devId}/override`
- Rows with `isHighMeetingLoad: true` show amber warning with `warningMessage`

**New file** `apps/web/src/components/sprint/MeetingLoadWarning.tsx`:
- Shows amber banner: "N developer(s) have reduced capacity this sprint"
- Expands to list each developer's `warningMessage`
- "Adjust Capacity" button that opens/focuses `CapacitySettingsPanel`

**New file** `apps/web/src/types/capacity.ts`:
```typescript
interface DeveloperCapacityItem {
  developerId: string
  displayName: string
  baseVelocity: number
  effectiveCapacityPts: number
  meetingOverheadPct: number
  ptoDays: number
  capacityPct: number
  isHighMeetingLoad: boolean
  warningMessage: string | null
}

interface TeamCapacityResponse {
  teamId: string
  meetingOverheadPct: number
  developers: DeveloperCapacityItem[]
}
```

**Edit** `apps/web/src/pages/SprintPlannerPage.tsx`:
- Add `useQuery` for `GET /api/capacity/team/default`
- Render `<CapacitySettingsPanel>` below the top button row (collapsible, default collapsed)
- Render `<MeetingLoadWarning>` when any developer `isHighMeetingLoad: true`
- VelocityCards `capacity` prop: use `effectiveCapacityPts` from capacity response instead of hardcoded `DEFAULT_CAPACITY = 40`

### Verification
- `python migrate.py` applies `0012` cleanly; duplicate `(developer_id, sprint_id)` override → `UniqueViolation`
- `PATCH /api/capacity/team/{id}/overhead` with `meetingOverheadPct: 0.20` → `GET` reflects `0.20`; Sprint Brain developer profile `safe_capacity_pts` reduced by 20%
- `PUT` capacity override with `capacityPct: 0.6` → `effectiveCapacityPts` = base * 0.6 * (1 - 0.20); `isHighMeetingLoad: true`; `warningMessage` non-null
- `meetingOverheadPct: 1.5` → 422
- P2 check (deferred): `GET /api/integrations/calendar/meetings/{team_id}` without calendar connected → 402

---

## Contract M — Multi-Team Management

**Goal:** Let leads and execs who manage multiple teams switch the active team context from the nav bar, view a unified health dashboard across all their teams, configure per-team Slack routing for automated alerts, and share developer velocity profiles across team assignments.

**Tracks:** 36 (DB), 37 (teams API + multi-dashboard service), 38 (Slack API + service), 39 (frontend team switcher + multi-dashboard), 40 (frontend Slack config in Settings)
**Waves:** 1 (DB), 2 (services), 3 (routers), 4 (frontend)
**Depends on:** Existing `Developer`, `Team`, `Organization` models; existing `SettingsPage.tsx`; existing `DashboardLayout.tsx`

**Current state:** Each user belongs to exactly one team (the org's default team). No team switcher in nav. No Slack integration. No multi-team dashboard. No `team_access_grants` table.

### DB Schema — Wave 1 (Track 36)

**New table** — new file `apps/api/src/models/team_access.py`:
```python
class TeamAccessGrant(Base):
    __tablename__ = "team_access_grants"

    id:           Mapped[uuid.UUID]  # PK
    developer_id: Mapped[uuid.UUID]  # FK developers.id, NOT NULL, ON DELETE CASCADE
    team_id:      Mapped[uuid.UUID]  # FK teams.id, NOT NULL, ON DELETE CASCADE
    granted_by:   Mapped[str]        # Clerk user id, NOT NULL
    granted_at:   Mapped[datetime]   # TIMESTAMP DEFAULT now()
```
Unique constraint on `(developer_id, team_id)`. Export `TeamAccessGrant` from `models/__init__.py`.

**New table** — new file `apps/api/src/models/slack_config.py`:
```python
class SlackConfig(Base):
    __tablename__ = "slack_configs"

    id:          Mapped[uuid.UUID]  # PK
    team_id:     Mapped[uuid.UUID]  # FK teams.id UNIQUE, NOT NULL
    webhook_url: Mapped[str]        # TEXT NOT NULL
    channel:     Mapped[str | None] # VARCHAR(100)
    alert_types: Mapped[list]       # JSONB DEFAULT ["high_risk_dependency","sprint_at_risk","retro_action_overdue"]
    is_active:   Mapped[bool]       # DEFAULT TRUE
    created_at:  Mapped[datetime]
```
Export `SlackConfig` from `models/__init__.py`.

**New migration** `apps/api/alembic/versions/0014_team_access_and_slack.py`:
```sql
-- up
CREATE TABLE IF NOT EXISTS team_access_grants (
    id           UUID PRIMARY KEY,
    developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    team_id      UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    granted_by   VARCHAR(255) NOT NULL,
    granted_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_team_access_grant
    ON team_access_grants(developer_id, team_id);
CREATE INDEX IF NOT EXISTS ix_team_access_dev_id
    ON team_access_grants(developer_id);

CREATE TABLE IF NOT EXISTS slack_configs (
    id          UUID PRIMARY KEY,
    team_id     UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    webhook_url TEXT NOT NULL,
    channel     VARCHAR(100),
    alert_types JSONB NOT NULL DEFAULT '["high_risk_dependency","sprint_at_risk","retro_action_overdue"]',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_slack_config_team
    ON slack_configs(team_id) WHERE is_active = TRUE;

-- down
DROP TABLE IF EXISTS slack_configs;
DROP TABLE IF EXISTS team_access_grants;
```

### Service Logic — Wave 2 (Track 37)

**New file** `apps/api/src/services/multi_team.py`:

```python
async def get_accessible_teams(
    clerk_user_id: str,
    clerk_org_id: str,
    db: AsyncSession,
) -> list[Team]:
    """
    Returns all teams the user has access to:
    1. The user's primary team (via Developer.team_id)
    2. Any teams in TeamAccessGrant where developer_id matches the user's Developer row
    All teams must belong to the same org. Deduplicated and sorted by team name.
    """

async def get_multi_team_summary(
    team_ids: list[uuid.UUID],
    db: AsyncSession,
) -> list[dict]:
    """
    For each team: compute health score (reuse compute_health_score from services/health.py),
    active sprint name, completion rate, active dependency count, last retro date.
    Returns list of team summary dicts sorted by health score ASC (worst first).
    """
```

### Service Logic — Wave 2 (Track 38)

**New file** `apps/api/src/services/slack.py`:

```python
import httpx

ALERT_TEMPLATES: dict[str, str] = {
    "high_risk_dependency": "⛔ *{team_name}*: High-risk dependency on `{ticket_key}` — {description}",
    "sprint_at_risk":       "⚠️ *{team_name}*: Sprint `{sprint_name}` is at risk — {reason}",
    "retro_action_overdue": "📋 *{team_name}*: Retro action overdue — {action}",
}

async def send_slack_alert(
    webhook_url: str,
    alert_type: str,
    payload: dict,
) -> bool:
    """
    Formats message from ALERT_TEMPLATES[alert_type] using payload.
    POSTs to webhook_url. Returns True on 200, False otherwise.
    Never raises — caller should log failures.
    """

async def send_test_message(webhook_url: str, team_name: str) -> bool:
    """Sends a simple "✅ AgileOS Slack connection verified for {team_name}" message."""

async def dispatch_alerts_for_team(
    team_id: uuid.UUID,
    alert_type: str,
    payload: dict,
    db: AsyncSession,
) -> bool:
    """
    Looks up active SlackConfig for team. If found and alert_type in config.alert_types,
    calls send_slack_alert(). Returns True if message sent, False if no config or disabled.
    """
```

### API Spec — Wave 3 (Track 37)

**New file** `apps/api/src/routers/teams.py`.
Register in `main.py`: `app.include_router(teams_router, prefix="/api/teams")`

#### `GET /api/teams`
```
Auth: any authenticated user
Response 200:
{
  "teams": [{
    "teamId":   string,
    "teamName": string,
    "isPrimary": boolean   ← true for the user's Developer.team_id team
  }]
}
Note: if user has no TeamAccessGrant rows, returns only their primary team.
```

#### `GET /api/teams/multi-dashboard`
```
Auth: require_role("lead")
Response 200:
{
  "teams": [TeamDashboardItem]
}
TeamDashboardItem:
{
  "teamId":            string,
  "teamName":          string,
  "healthScore":       number (0–100),
  "activeSprintName":  string | null,
  "completionRate":    number (0.0–1.0),
  "activeDepsCount":   number,
  "lastRetroDate":     string | null,
  "ragStatus":         "green" | "amber" | "red"
}
```

#### `POST /api/teams/{team_id}/access`
```
Auth: require_role("lead")
Request: { "developerClerkUserId": string }
Response 201: { "granted": true, "teamId": string, "developerId": string }
Response 404: developer not found by clerkUserId
Response 409: access already granted
```

#### `DELETE /api/teams/{team_id}/access/{developer_id}`
```
Auth: require_role("lead")
Response 200: { "revoked": true }
Response 404: grant not found
```

### API Spec — Wave 3 (Track 38)

**New file** `apps/api/src/routers/slack.py`.
Register in `main.py`: `app.include_router(slack_router, prefix="/api/teams")`
(Nested under `/api/teams` prefix for logical grouping.)

#### `GET /api/teams/{team_id}/slack`
```
Auth: require_role("lead")
Response 200:
{
  "configured": boolean,
  "channel":    string | null,
  "alertTypes": string[],
  "isActive":   boolean
}
```

#### `PUT /api/teams/{team_id}/slack`
```
Auth: require_role("lead")
Request:
{
  "webhookUrl": string,
  "channel":    string | null,
  "alertTypes": string[]
}
Response 200: same shape as GET response
Response 422: webhookUrl not a valid Slack webhook URL (must start with https://hooks.slack.com/)
```

#### `DELETE /api/teams/{team_id}/slack`
```
Auth: require_role("lead")
Response 200: { "deleted": true }
Response 404: no Slack config found
```

#### `POST /api/teams/{team_id}/slack/test`
```
Auth: require_role("lead")
Response 200: { "sent": true }
Response 402: no Slack config or config inactive
Response 502: Slack webhook returned non-200
```

All response models use `ConfigDict(alias_generator=to_camel, populate_by_name=True)`.

### Frontend Spec — Wave 4 (Track 39)

**New file** `apps/web/src/contexts/TeamContext.tsx`:
```typescript
interface TeamContextValue {
  activeTeamId: string         // UUID or 'default'
  activeTeamName: string
  teams: TeamListItem[]
  setActiveTeam: (teamId: string) => void
}
```
- On mount: fetches `GET /api/teams` to populate `teams`
- `activeTeamId` stored in `localStorage` under `'aos_active_team_id'`; defaults to `'default'` if none stored
- `setActiveTeam` updates localStorage and re-triggers any queries whose `queryKey` includes `activeTeamId`

**New file** `apps/web/src/components/TeamSwitcher.tsx`:
- Dropdown showing all teams from `TeamContext.teams`
- Current team displayed as selected value
- On change: calls `setActiveTeam`, then calls `window.location.reload()` to flush all cached data
- Only renders if `teams.length > 1`

**Edit** `apps/web/src/layouts/DashboardLayout.tsx`:
- Wrap with `<TeamProvider>`
- Render `<TeamSwitcher />` below the AgileOS logo, above nav links
- All `NavLink` hrefs are unchanged (team context flows via query params or context, not URL)

**New file** `apps/web/src/pages/MultiTeamDashboardPage.tsx`:
- Fetches `GET /api/teams/multi-dashboard`
- Renders a card grid using the existing `TeamHealthCard` component style (one card per team)
- Worst health teams at top (sorted by `ragStatus`: red → amber → green)
- Clicking a card navigates to `/app/velocity-mirror` with `?teamId={teamId}`
- 403: "Multi-team view requires lead role or higher"
- Empty state: "No additional teams found"

**New file** `apps/web/src/types/multiTeam.ts`:
```typescript
interface TeamListItem { teamId: string; teamName: string; isPrimary: boolean }
interface TeamDashboardItem {
  teamId: string; teamName: string; healthScore: number
  activeSprintName: string | null; completionRate: number
  activeDepsCount: number; lastRetroDate: string | null
  ragStatus: 'green' | 'amber' | 'red'
}
```

**Edit** `apps/web/src/App.tsx`:
- Add route `multi-team` → `<MultiTeamDashboardPage />`

**Edit** `apps/web/src/layouts/DashboardLayout.tsx`:
- Add nav link "Multi-Team" (lead+ only) pointing to `/app/multi-team`

### Frontend Spec — Wave 4 (Track 40)

**Edit** `apps/web/src/pages/SettingsPage.tsx` — add Slack configuration card:
- Fetches `GET /api/teams/default/slack` on mount
- Shows "Not configured" badge or "Active" badge
- Webhook URL input + channel input + alert type checkboxes (3 types)
- Save button → `PUT /api/teams/default/slack`
- Test button → `POST /api/teams/default/slack/test` → shows "✅ Test message sent" or "❌ Failed"
- Delete button (only when configured) → `DELETE /api/teams/default/slack`
- `422` validation error displayed inline

### Verification
- `python migrate.py` applies `0014` cleanly; duplicate `(developer_id, team_id)` grant → `UniqueViolation`
- `GET /api/teams` returns primary team for user with no grants; returns both teams after grant added
- `GET /api/teams/multi-dashboard` → developer role → 403; lead role → 200 with correct health scores
- `PUT /api/teams/{id}/slack` with valid webhook → `GET` returns config; `POST /test` → Slack message received; invalid URL → 422
- Team switcher renders when 2+ teams accessible; switching team updates `localStorage`; page reload applies new team context
- Slack config card in Settings: save/test/delete all work; test failure (bad webhook) shows error state

---

## Shared File Collision Matrix

| File | Touched By | Rule |
|---|---|---|
| `apps/api/src/main.py` | Tracks 28, 31, 37, 38 | One registration pass at end of Wave 3 |
| `apps/api/src/models/__init__.py` | Tracks 25, 30, 36 | One export-update pass at end of Wave 1 |
| `apps/web/src/App.tsx` | Tracks 29, 39 | One route-add pass at end of Wave 4 |
| `apps/web/src/layouts/DashboardLayout.tsx` | Track 39 only | Single agent owns this file |
| `apps/web/src/pages/SprintPlannerPage.tsx` | Track 32 | Read current state (post Phase 1) before editing |
| `apps/web/src/pages/SettingsPage.tsx` | Track 40 | Read current state (post Phase 1) before editing |
| `apps/api/src/models/team.py` | Tracks 25, 30 | Both column additions in migration 0012; do not re-run 0011 changes |
