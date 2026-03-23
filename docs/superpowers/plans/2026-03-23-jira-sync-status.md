# Jira Sync Status Tracking Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `jira_sync_statuses` table that tracks per-team sync state (pending/running/success/failed), expose it via a new API endpoint, and add a Railway worker service config.

**Architecture:** A new `JiraSyncStatus` model (one row per team, upserted on each state transition) is written by `sync_jira_team` at task start/end/failure, and by the router at enqueue time. A new `GET /sync-status/{team_id}` endpoint reads this table. A `railway-worker.toml` configures the Celery worker as a separate Railway service.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (sync ORM in tasks, async in router), Alembic, Celery, uv for running tests.

**Spec:** `docs/superpowers/specs/2026-03-23-jira-sync-status-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/models/jira_sync_status.py` | **Create** | `JiraSyncStatus` ORM model |
| `src/models/__init__.py` | **Modify** | Import + export new model |
| `alembic/versions/0003_add_jira_sync_status.py` | **Create** | Migration: create `jira_sync_statuses` table |
| `src/integrations/jira/sync.py` | **Modify** | Write status at task start, success, failure |
| `src/integrations/jira/router.py` | **Modify** | Write `pending` at enqueue; add sync-status endpoint |
| `tests/test_jira_sync.py` | **Modify** | Add status-tracking tests |
| `tests/test_jira_router.py` | **Modify** | Add sync-status endpoint tests |
| `railway-worker.toml` | **Create** | Railway worker service config |

---

## Chunk 1: Model, Migration, and Status Tracking in Task

### Task 1: `JiraSyncStatus` model

**Files:**
- Create: `apps/api/src/models/jira_sync_status.py`
- Modify: `apps/api/src/models/__init__.py`

- [ ] **Step 1: Write the failing test**

  Add to `apps/api/tests/test_jira_sync.py`:

  ```python
  def test_jira_sync_status_model_upsert():
      """JiraSyncStatus can be created and updated using a sync session."""
      from src.models.jira_sync_status import JiraSyncStatus
      import uuid

      db, engine = _make_sync_session()
      try:
          # Need a team to satisfy the FK — use a real Team row
          from src.models.organization import Organization
          from src.models.team import Team
          org_id = uuid.uuid4()
          team_id = uuid.uuid4()
          org = Organization(id=org_id, clerk_org_id="org_ss1", name="SS1", slug="ss1", use_managed_key=False)
          team = Team(id=team_id, organization_id=org_id, name="TT1", sprint_length_days=14)
          db.add_all([org, team])
          db.commit()

          # Create
          row = JiraSyncStatus(team_id=team_id, status="pending")
          db.add(row)
          db.commit()

          fetched = db.get(JiraSyncStatus, team_id)
          assert fetched is not None
          assert fetched.status == "pending"
          assert fetched.last_synced_at is None

          # Update
          fetched.status = "success"
          db.commit()
          db.expire_all()
          assert db.get(JiraSyncStatus, team_id).status == "success"
      finally:
          db.close()
          _cleanup(engine)
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  cd apps/api && uv run pytest tests/test_jira_sync.py::test_jira_sync_status_model_upsert -v
  ```

  Expected: `ImportError` or `ModuleNotFoundError` — model doesn't exist yet.

- [ ] **Step 3: Create the model**

  Create `apps/api/src/models/jira_sync_status.py`:

  ```python
  import uuid
  from datetime import datetime
  from sqlalchemy import String, DateTime, ForeignKey, Text
  from sqlalchemy.orm import Mapped, mapped_column
  from sqlalchemy.dialects.postgresql import UUID
  from src.database import Base


  class JiraSyncStatus(Base):
      __tablename__ = "jira_sync_statuses"

      team_id: Mapped[uuid.UUID] = mapped_column(
          UUID(as_uuid=True), ForeignKey("teams.id"), primary_key=True
      )
      status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
      last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
      error: Mapped[str | None] = mapped_column(Text, nullable=True)
      updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
  ```

- [ ] **Step 4: Register model in `src/models/__init__.py`**

  Add after the `JiraConnection` import line:

  ```python
  from src.models.jira_sync_status import JiraSyncStatus
  ```

  Add `"JiraSyncStatus"` to the `__all__` list.

- [ ] **Step 5: Run test to verify it passes**

  ```bash
  cd apps/api && uv run pytest tests/test_jira_sync.py::test_jira_sync_status_model_upsert -v
  ```

  Expected: `PASSED`

- [ ] **Step 6: Commit**

  ```bash
  git add apps/api/src/models/jira_sync_status.py apps/api/src/models/__init__.py apps/api/tests/test_jira_sync.py
  git commit -m "feat: add JiraSyncStatus model"
  ```

---

### Task 2: Alembic migration

**Files:**
- Create: `apps/api/alembic/versions/0003_add_jira_sync_status.py`

- [ ] **Step 1: Create the migration file**

  Create `apps/api/alembic/versions/0003_add_jira_sync_status.py`:

  ```python
  """add jira_sync_statuses table

  Revision ID: 0003
  Revises: init003
  Create Date: 2026-03-23
  """
  from alembic import op
  import sqlalchemy as sa
  from sqlalchemy.dialects import postgresql

  revision = 'init004'
  down_revision = 'init003'
  branch_labels = None
  depends_on = None


  def upgrade() -> None:
      op.create_table(
          'jira_sync_statuses',
          sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id'), primary_key=True),
          sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
          sa.Column('last_synced_at', sa.DateTime, nullable=True),
          sa.Column('error', sa.Text, nullable=True),
          sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
      )


  def downgrade() -> None:
      op.drop_table('jira_sync_statuses')
  ```

- [ ] **Step 2: Verify Alembic can parse the migration**

  ```bash
  cd apps/api && uv run alembic check
  ```

  Expected: No errors (or warning that DB is ahead — that's fine locally without a live DB).
  If `alembic check` requires a live DB and fails, run instead:
  ```bash
  cd apps/api && uv run python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; c = Config('alembic.ini'); sd = ScriptDirectory.from_config(c); print('OK')"
  ```
  Expected: `OK`

- [ ] **Step 3: Commit**

  ```bash
  git add apps/api/alembic/versions/0003_add_jira_sync_status.py
  git commit -m "feat: add migration for jira_sync_statuses table"
  ```

---

### Task 3: Status tracking in `sync_jira_team`

**Files:**
- Modify: `apps/api/src/integrations/jira/sync.py`
- Modify: `apps/api/tests/test_jira_sync.py`

The `sync_jira_team` task writes status at three points:
- Top of task body → `running`
- After `db.commit()` success → `success` with `last_synced_at`
- In the `except` block before `raise self.retry()` → `failed` with error message

A private helper `_upsert_sync_status` handles the DB write to avoid repetition.

- [ ] **Step 1: Write the failing test**

  Add to `apps/api/tests/test_jira_sync.py`:

  ```python
  def test_sync_jira_team_writes_running_then_success_status():
      """sync_jira_team writes 'running' at start and 'success' on completion."""
      from src.models.organization import Organization
      from src.models.team import Team
      from src.models.jira_connection import JiraConnection
      from src.models.jira_sync_status import JiraSyncStatus
      from src.integrations.jira.sync import sync_jira_team
      import uuid
      from unittest.mock import patch, MagicMock

      db, engine = _make_sync_session()
      try:
          org_id = uuid.uuid4()
          team_id = uuid.uuid4()
          org = Organization(id=org_id, clerk_org_id="org_st1", name="ST1", slug="st1", use_managed_key=False)
          team = Team(id=team_id, organization_id=org_id, name="TTst1", sprint_length_days=14, jira_board_id="20")
          conn = JiraConnection(
              id=uuid.uuid4(),
              organization_id=org_id,
              jira_cloud_id="cst1",
              jira_cloud_url="https://st1.atlassian.net",
              encrypted_access_token="x",
              encrypted_refresh_token="x",
              is_active=True,
          )
          db.add_all([org, team, conn])
          db.commit()

          mock_client = MagicMock()
          mock_client.get_users = MagicMock(return_value=[])
          mock_client.get_sprints = MagicMock(return_value=[])

          with patch("src.integrations.jira.sync._get_sync_session", return_value=db):
              with patch("src.integrations.jira.sync._get_fresh_client", return_value=mock_client):
                  import asyncio
                  with patch("asyncio.get_event_loop") as mock_loop:
                      mock_loop.return_value.run_until_complete = lambda coro: []
                      # Call the task function directly (not via .delay)
                      sync_jira_team(str(team_id))

          db.expire_all()
          status_row = db.get(JiraSyncStatus, team_id)
          assert status_row is not None
          assert status_row.status == "success"
          assert status_row.last_synced_at is not None
          assert status_row.error is None
      finally:
          db.close()
          _cleanup(engine)


  def test_sync_jira_team_writes_failed_status_on_error():
      """sync_jira_team writes 'failed' status when an exception occurs."""
      from src.models.organization import Organization
      from src.models.team import Team
      from src.models.jira_connection import JiraConnection
      from src.models.jira_sync_status import JiraSyncStatus
      from src.integrations.jira.sync import sync_jira_team
      import uuid
      from unittest.mock import patch, MagicMock
      from celery.exceptions import Retry

      db, engine = _make_sync_session()
      try:
          org_id = uuid.uuid4()
          team_id = uuid.uuid4()
          org = Organization(id=org_id, clerk_org_id="org_st2", name="ST2", slug="st2", use_managed_key=False)
          team = Team(id=team_id, organization_id=org_id, name="TTst2", sprint_length_days=14, jira_board_id="21")
          conn = JiraConnection(
              id=uuid.uuid4(),
              organization_id=org_id,
              jira_cloud_id="cst2",
              jira_cloud_url="https://st2.atlassian.net",
              encrypted_access_token="x",
              encrypted_refresh_token="x",
              is_active=True,
          )
          db.add_all([org, team, conn])
          db.commit()

          with patch("src.integrations.jira.sync._get_sync_session", return_value=db):
              with patch("src.integrations.jira.sync._get_fresh_client", side_effect=RuntimeError("boom")):
                  try:
                      sync_jira_team(str(team_id))
                  except (Retry, RuntimeError):
                      pass  # Expected — task retries on failure

          db.expire_all()
          status_row = db.get(JiraSyncStatus, team_id)
          assert status_row is not None
          assert status_row.status == "failed"
          assert "boom" in status_row.error
      finally:
          db.close()
          _cleanup(engine)
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  cd apps/api && uv run pytest tests/test_jira_sync.py::test_sync_jira_team_writes_running_then_success_status tests/test_jira_sync.py::test_sync_jira_team_writes_failed_status_on_error -v
  ```

  Expected: Both `FAILED` — status rows not being written yet.

- [ ] **Step 3: Add `_upsert_sync_status` helper and update `sync_jira_team`**

  In `apps/api/src/integrations/jira/sync.py`, add the helper after `_parse_datetime`:

  ```python
  def _upsert_sync_status(
      db: Session,
      team_id: str,
      status: str,
      error: str | None = None,
      last_synced_at: datetime | None = None,
  ) -> None:
      """Upsert a JiraSyncStatus row for the given team."""
      from src.models.jira_sync_status import JiraSyncStatus

      team_uuid = uuid.UUID(team_id)
      row = db.get(JiraSyncStatus, team_uuid)
      if row is None:
          row = JiraSyncStatus(team_id=team_uuid)
          db.add(row)
      row.status = status
      row.error = error
      row.updated_at = datetime.utcnow()
      if last_synced_at is not None:
          row.last_synced_at = last_synced_at
      db.flush()
  ```

  Then update `sync_jira_team` to write status at each stage. Replace the existing function body so it reads:

  ```python
  @celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
  def sync_jira_team(self, team_id: str):
      """Full sync of all sprints and issues for a team from Jira."""
      import asyncio
      from src.models.team import Team
      from src.models.jira_connection import JiraConnection

      logger.info("Starting full Jira sync for team %s", team_id)
      db = _get_sync_session()
      try:
          _upsert_sync_status(db, team_id, "running")
          db.commit()

          team = db.get(Team, uuid.UUID(team_id))
          if not team or not team.jira_board_id:
              logger.warning("Team %s not found or has no Jira board configured", team_id)
              _upsert_sync_status(db, team_id, "failed", error="Team not found or no board configured")
              db.commit()
              return

          connection = db.execute(
              select(JiraConnection)
              .where(
                  JiraConnection.organization_id == team.organization_id,
                  JiraConnection.is_active == True,
              )
          ).scalar_one_or_none()

          if not connection:
              logger.warning("No active Jira connection for org of team %s", team_id)
              _upsert_sync_status(db, team_id, "failed", error="No active Jira connection")
              db.commit()
              return

          client = _get_fresh_client(connection)

          users = asyncio.get_event_loop().run_until_complete(client.get_users())
          _upsert_team_members(db, team, users)

          sprints = asyncio.get_event_loop().run_until_complete(
              client.get_sprints(team.jira_board_id)
          )
          from src.models.sprint import Sprint as SprintModel

          for jira_sprint in sprints:
              sprint_obj = _upsert_sprint(db, team, jira_sprint)
              issues = asyncio.get_event_loop().run_until_complete(
                  client.get_sprint_issues(str(jira_sprint["id"]))
              )
              if sprint_obj:
                  _upsert_issues(db, team, sprint_obj, issues)

          connection.last_synced_at = datetime.utcnow()
          _upsert_sync_status(db, team_id, "success", last_synced_at=datetime.utcnow())
          db.commit()
          logger.info("Full Jira sync complete for team %s", team_id)

      except Exception as exc:
          db.rollback()
          logger.exception("Jira sync failed for team %s: %s", team_id, exc)
          try:
              _upsert_sync_status(db, team_id, "failed", error=str(exc))
              db.commit()
          except Exception:
              pass  # Don't mask the original exception
          raise self.retry(exc=exc)
      finally:
          db.close()
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  cd apps/api && uv run pytest tests/test_jira_sync.py::test_sync_jira_team_writes_running_then_success_status tests/test_jira_sync.py::test_sync_jira_team_writes_failed_status_on_error -v
  ```

  Expected: Both `PASSED`

- [ ] **Step 5: Run full sync test suite to confirm no regressions**

  ```bash
  cd apps/api && uv run pytest tests/test_jira_sync.py -v
  ```

  Expected: All tests `PASSED`

- [ ] **Step 6: Commit**

  ```bash
  git add apps/api/src/integrations/jira/sync.py apps/api/tests/test_jira_sync.py
  git commit -m "feat: write sync status to jira_sync_statuses in sync_jira_team"
  ```

---

## Chunk 2: Router Endpoint and Railway Config

### Task 4: Sync-status endpoint + pending write at enqueue

**Files:**
- Modify: `apps/api/src/integrations/jira/router.py`
- Modify: `apps/api/tests/test_jira_router.py`

Two changes to `router.py`:
1. `POST /sync` and `POST /board-selection` write `pending` to `jira_sync_statuses` before calling `.delay()`
2. New `GET /sync-status/{team_id}` endpoint reads from the table

- [ ] **Step 1: Write failing tests**

  Add to `apps/api/tests/test_jira_router.py`:

  ```python
  @pytest.mark.asyncio
  async def test_sync_status_404_when_never_synced(tmp_db):
      """GET /sync-status/{team_id} returns 404 when no status row exists."""
      import uuid
      team_id = str(uuid.uuid4())
      with _patch_clerk():
          async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
              resp = await client.get(
                  f"/api/integrations/jira/sync-status/{team_id}",
                  headers={"Authorization": "Bearer tok"},
              )
      assert resp.status_code == 404


  @pytest.mark.asyncio
  async def test_sync_status_returns_row(tmp_db):
      """GET /sync-status/{team_id} returns the status when a row exists."""
      import uuid
      from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
      from src.database import Base, get_db
      from src.models.jira_sync_status import JiraSyncStatus
      from src.models.organization import Organization
      from src.models.team import Team

      engine = create_async_engine("sqlite+aiosqlite:///:memory:")
      async with engine.begin() as conn:
          await conn.run_sync(Base.metadata.create_all)
      Session = async_sessionmaker(engine, expire_on_commit=False)

      # Pre-populate DB with an org, team, and sync status row
      org_id = uuid.uuid4()
      team_id = uuid.uuid4()
      async with Session() as session:
          org = Organization(id=org_id, clerk_org_id="org_r1", name="R1", slug="r1", use_managed_key=False)
          team = Team(id=team_id, organization_id=org_id, name="TR1", sprint_length_days=14)
          row = JiraSyncStatus(team_id=team_id, status="success")
          session.add_all([org, team, row])
          await session.commit()

      async def override_get_db():
          async with Session() as s:
              yield s

      from src.main import app as _app
      _app.dependency_overrides[get_db] = override_get_db

      try:
          with _patch_clerk():
              async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
                  resp = await client.get(
                      f"/api/integrations/jira/sync-status/{team_id}",
                      headers={"Authorization": "Bearer tok"},
                  )
          assert resp.status_code == 200
          body = resp.json()
          assert body["status"] == "success"
          assert body["team_id"] == str(team_id)
      finally:
          _app.dependency_overrides.pop(get_db, None)
          async with engine.begin() as conn:
              await conn.run_sync(Base.metadata.drop_all)
          await engine.dispose()


  @pytest.mark.asyncio
  async def test_sync_status_requires_auth():
      """GET /sync-status/{team_id} returns 401/403 without auth."""
      import uuid
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          resp = await client.get(f"/api/integrations/jira/sync-status/{uuid.uuid4()}")
      assert resp.status_code in (401, 403)
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  cd apps/api && uv run pytest tests/test_jira_router.py::test_sync_status_404_when_never_synced tests/test_jira_router.py::test_sync_status_returns_row tests/test_jira_router.py::test_sync_status_requires_auth -v
  ```

  Expected: `FAILED` — endpoint doesn't exist yet (404 from routing, not logic).

- [ ] **Step 3: Add the sync-status endpoint to `router.py`**

  Add this import at the top of `router.py` (after existing imports):

  ```python
  from src.database import get_db  # already imported via other deps, verify it exists
  ```

  _(If `get_db` is already imported, skip.)_

  Add the new endpoint at the end of `router.py`:

  ```python
  @router.get("/sync-status/{team_id}")
  async def get_sync_status(
      team_id: str,
      user_id: str = Depends(get_current_user_id),
      db: AsyncSession = Depends(get_db),
  ):
      """Return the current Jira sync status for a team."""
      try:
          team_uuid = uuid.UUID(team_id)
      except ValueError:
          raise HTTPException(status_code=400, detail="Invalid team_id")

      from src.models.jira_sync_status import JiraSyncStatus
      row = await db.get(JiraSyncStatus, team_uuid)
      if not row:
          raise HTTPException(status_code=404, detail="No sync status found for this team")

      return {
          "team_id": str(row.team_id),
          "status": row.status,
          "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
          "error": row.error,
      }
  ```

- [ ] **Step 4: Add `db` dependency + pending write to `POST /sync`**

  The existing `trigger_sync` endpoint doesn't have a `db` session. Update it to write `pending` before enqueuing:

  ```python
  @router.post("/sync")
  async def trigger_sync(
      team_id: str,
      user_id: str = Depends(get_current_user_id),
      db: AsyncSession = Depends(get_db),
  ):
      """Enqueue a background Celery task to sync a team's Jira data."""
      try:
          team_uuid = uuid.UUID(team_id)
      except ValueError:
          raise HTTPException(status_code=400, detail="Invalid team_id")

      from src.models.jira_sync_status import JiraSyncStatus
      row = await db.get(JiraSyncStatus, team_uuid)
      if row is None:
          db.add(JiraSyncStatus(team_id=team_uuid, status="pending"))
      else:
          row.status = "pending"
          row.error = None
      await db.commit()

      from src.integrations.jira.sync import sync_jira_team
      task = sync_jira_team.delay(team_id)
      return {"task_id": task.id, "status": "queued"}
  ```

- [ ] **Step 5: Add pending write to `POST /board-selection`**

  In `save_board_selection`, after `await db.commit()` (after saving `team.jira_board_id`) and before the `try: sync_jira_team.delay(...)` block, add:

  ```python
  from src.models.jira_sync_status import JiraSyncStatus
  status_row = await db.get(JiraSyncStatus, team.id)
  if status_row is None:
      db.add(JiraSyncStatus(team_id=team.id, status="pending"))
  else:
      status_row.status = "pending"
      status_row.error = None
  await db.commit()
  ```

- [ ] **Step 6: Run tests to verify they pass**

  ```bash
  cd apps/api && uv run pytest tests/test_jira_router.py::test_sync_status_404_when_never_synced tests/test_jira_router.py::test_sync_status_returns_row tests/test_jira_router.py::test_sync_status_requires_auth -v
  ```

  Expected: All `PASSED`

- [ ] **Step 7: Run full router test suite to confirm no regressions**

  ```bash
  cd apps/api && uv run pytest tests/test_jira_router.py -v
  ```

  Expected: All tests `PASSED`

- [ ] **Step 8: Commit**

  ```bash
  git add apps/api/src/integrations/jira/router.py apps/api/tests/test_jira_router.py
  git commit -m "feat: add sync-status endpoint and pending write at enqueue"
  ```

---

### Task 5: Railway worker service config

**Files:**
- Create: `apps/api/railway-worker.toml`

- [ ] **Step 1: Create the file**

  Create `apps/api/railway-worker.toml`:

  ```toml
  [deploy]
  startCommand = "sh -c 'celery -A src.worker worker --beat --loglevel=info'"
  restartPolicyType = "on_failure"
  restartPolicyMaxRetries = 5
  ```

  No `preDeployCommand` — migrations are handled by the web service's `railway.toml`.

- [ ] **Step 2: Verify the file parses as valid TOML**

  ```bash
  cd apps/api && python -c "import tomllib; tomllib.load(open('railway-worker.toml', 'rb')); print('valid')"
  ```

  Expected: `valid`

- [ ] **Step 3: Run the full test suite one final time**

  ```bash
  cd apps/api && uv run pytest -v
  ```

  Expected: All tests `PASSED`

- [ ] **Step 4: Commit**

  ```bash
  git add apps/api/railway-worker.toml
  git commit -m "feat: add railway-worker.toml for Celery worker service"
  ```
