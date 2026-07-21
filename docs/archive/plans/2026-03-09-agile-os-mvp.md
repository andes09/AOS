# AgileOS MVP Implementation Plan (Sprint Brain + Velocity Mirror)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a working Sprint Brain + Velocity Mirror SaaS product with Jira integration in 1–2 months, capable of onboarding paying beta teams.

**Architecture:** Python FastAPI backend + React/Vite frontend in a pnpm monorepo. PostgreSQL for persistence, Redis for job queues. Jira is the sole P0 integration. Claude API with customer-owned keys (BYOK) powers Sprint Brain recommendations.

**Tech Stack:**
- Backend: Python 3.12, FastAPI, SQLAlchemy (async), Alembic, Celery + Redis
- Frontend: React 18, Vite, TanStack Query, Recharts, Clerk (auth)
- Database: PostgreSQL 16
- AI: Anthropic Claude API (BYOK — customer supplies key)
- Deploy: Vercel (frontend) + Railway (API + PostgreSQL + Redis)
- Monorepo: pnpm workspaces

---

## ⚠️ Architectural Decisions & My Pushback

**On BYOK for MVP:** Good for beta (users are technical, cost stays $0 for you). However, design the key storage layer so you can flip to a managed-key model later without a rewrite. I've planned for this.

**On validation phase:** Skipping the "zero-code manual MVP" from the PRD. You already have 40+ practitioner validations. Every week without code is a week without compounding data. Start building now.

**On scope:** MVP = Sprint Brain + Velocity Mirror only. Scope Cop, Dependency Radar, and Retrospective AI are in the full plan. Resist the urge to build them early — they share the same data models, so nothing is wasted by waiting.

---

## 🤖 Proposed Agents to Create

These agents do not yet exist and need to be created before or during execution of the tracks that use them.

### Agent: `jira-integration-agent`
**Purpose:** Owns everything related to the Jira OAuth2 connection and data sync.
**Skills to give it:**
- Jira REST API v3 (sprints, issues, users, boards, projects)
- OAuth2 authorization code flow with PKCE
- FastAPI route implementation
- SQLAlchemy async models and queries
- Celery task design for background sync jobs
- Webhook registration and verification

### Agent: `velocity-engine-agent`
**Purpose:** Builds the statistical core of Sprint Brain — per-developer velocity profiles and sprint capacity modelling.
**Skills to give it:**
- Python data analysis with pandas and numpy
- Per-developer velocity profiling by ticket type and domain
- Sprint capacity modelling (PTO, meetings, part-time)
- Confidence interval calculation
- SQLAlchemy queries for aggregating historical sprint data

### Agent: `dashboard-builder-agent`
**Purpose:** Builds all React dashboard UI components — sprint planner wizard, velocity cards, live burndown, alert feed.
**Skills to give it:**
- React 18 with hooks and context
- Recharts for data visualisation (line, bar, area, radial)
- TanStack Query for server state management
- Server-Sent Events (SSE) for live dashboard updates
- Responsive layout with CSS Grid/Flexbox
- Form handling with React Hook Form + Zod

---

## Parallel Execution Map

These tracks can run concurrently. Dependencies are noted per task.

```
Week 1:  [Track A] [Track B] [Track G] ← all independent, run in parallel
Week 2:  [Track C] [Track D] [Track E] ← depend on A+B; D+E can parallel
Week 3:  [Track F] [Track H start] ← F depends on B+C; H depends on G+F
Week 4:  [Track H finish] [Track I] ← I depends on G+D
Week 5-6: [Track J] ← depends on all above
```

---

## Track A: Monorepo Foundation
**Independent. Run in Week 1.**
**Owner: You or Claude**

### Task A1: Scaffold monorepo structure

**Files:**
- Create: `pnpm-workspace.yaml`
- Create: `package.json` (root)
- Create: `.gitignore`
- Create: `docker-compose.yml`
- Create: `.env.example`

**Step 1: Create root package.json**
```json
{
  "name": "agile-os",
  "private": true,
  "version": "0.0.1",
  "scripts": {
    "dev:web": "pnpm --filter web dev",
    "dev:landing": "pnpm --filter landing dev",
    "build:web": "pnpm --filter web build",
    "build:landing": "pnpm --filter landing build"
  },
  "engines": {
    "node": ">=20.0.0",
    "pnpm": ">=9.0.0"
  }
}
```

**Step 2: Create pnpm-workspace.yaml**
```yaml
packages:
  - 'apps/*'
  - 'LandingPage'
```

**Step 3: Create docker-compose.yml for local dev**
```yaml
version: '3.9'
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: agileos
      POSTGRES_PASSWORD: agileos_dev
      POSTGRES_DB: agileos
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

**Step 4: Create .env.example**
```env
# Database
DATABASE_URL=postgresql+asyncpg://agileos:agileos_dev@localhost:5432/agileos
DATABASE_URL_SYNC=postgresql://agileos:agileos_dev@localhost:5432/agileos

# Redis
REDIS_URL=redis://localhost:6379/0

# Clerk (auth)
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_WEBHOOK_SECRET=whsec_...

# Jira OAuth
JIRA_CLIENT_ID=
JIRA_CLIENT_SECRET=
JIRA_REDIRECT_URI=http://localhost:8000/api/integrations/jira/callback

# Encryption (for storing customer API keys)
ENCRYPTION_KEY=  # 32-byte hex string: openssl rand -hex 32

# App
ENVIRONMENT=development
FRONTEND_URL=http://localhost:5174
API_URL=http://localhost:8000
```

**Step 5: Move LandingPage to apps if not already done, create apps/ dir**
```bash
mkdir -p apps
```

**Step 6: Start Docker services**
```bash
docker compose up -d
```
Expected: postgres and redis containers running. Verify: `docker compose ps`

**Step 7: Commit**
```bash
git init
git add pnpm-workspace.yaml package.json docker-compose.yml .env.example .gitignore
git commit -m "feat: initialize monorepo with pnpm workspaces"
```

---

## Track B: FastAPI Backend Scaffold
**Independent. Run in Week 1 parallel with Track A and G.**
**Owner: You or Claude**
**Agent: none needed for scaffold**

### Task B1: Bootstrap FastAPI project

**Files:**
- Create: `apps/api/` (full directory)
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/src/main.py`
- Create: `apps/api/src/config.py`
- Create: `apps/api/src/database.py`

**Step 1: Create pyproject.toml**
```toml
[project]
name = "agile-os-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.30.0",
    "alembic>=1.13.0",
    "pydantic>=2.8.0",
    "pydantic-settings>=2.4.0",
    "python-dotenv>=1.0.0",
    "httpx>=0.27.0",
    "celery[redis]>=5.4.0",
    "redis>=5.0.0",
    "clerk-backend-api>=1.0.0",
    "cryptography>=43.0.0",
    "anthropic>=0.34.0",
    "pandas>=2.2.0",
    "numpy>=2.1.0",
    "python-jose[cryptography]>=3.3.0",
    "svix>=1.20.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-httpx>=0.30.0",
    "httpx>=0.27.0",
    "factory-boy>=3.3.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 2: Install dependencies**
```bash
cd apps/api
pip install uv
uv sync
```
Expected: all packages installed in .venv

**Step 3: Create src/config.py**
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    database_url_sync: str
    redis_url: str = "redis://localhost:6379/0"

    clerk_secret_key: str
    clerk_publishable_key: str
    clerk_webhook_secret: str

    jira_client_id: str = ""
    jira_client_secret: str = ""
    jira_redirect_uri: str = "http://localhost:8000/api/integrations/jira/callback"

    encryption_key: str  # 32-byte hex string

    environment: str = "development"
    frontend_url: str = "http://localhost:5174"
    api_url: str = "http://localhost:8000"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

settings = Settings()
```

**Step 4: Create src/database.py**
```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.config import settings

engine = create_async_engine(settings.database_url, echo=not settings.is_production)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
```

**Step 5: Create src/main.py**
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.config import settings

app = FastAPI(
    title="AgileOS API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}
```

**Step 6: Run server**
```bash
cd apps/api
uv run uvicorn src.main:app --reload --port 8000
```
Expected: `Uvicorn running on http://127.0.0.1:8000`

**Step 7: Verify health endpoint**
```bash
curl http://localhost:8000/health
```
Expected: `{"status":"ok","environment":"development"}`

**Step 8: Commit**
```bash
git add apps/api/
git commit -m "feat: scaffold FastAPI backend with config and database connection"
```

---

### Task B2: Clerk JWT authentication middleware

**Files:**
- Create: `apps/api/src/auth.py`
- Modify: `apps/api/src/main.py`

**Step 1: Write failing test**
```python
# tests/test_auth.py
import pytest
from httpx import AsyncClient
from src.main import app

@pytest.mark.asyncio
async def test_protected_route_requires_auth():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/me")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_health_does_not_require_auth():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
```

**Step 2: Run test to verify it fails**
```bash
cd apps/api && uv run pytest tests/test_auth.py -v
```
Expected: FAIL — `/api/me` route doesn't exist yet

**Step 3: Create src/auth.py**
```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from clerk_backend_api import Clerk
from src.config import settings
import httpx

security = HTTPBearer()
clerk = Clerk(bearer_auth=settings.clerk_secret_key)

async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Verify Clerk JWT and return the user ID (sub claim)."""
    token = credentials.credentials
    try:
        # Verify token with Clerk
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.clerk.com/v1/tokens/verify",
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                params={"token": token},
            )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        data = response.json()
        return data["sub"]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
```

**Step 4: Add /api/me route to main.py**
```python
from src.auth import get_current_user_id

@app.get("/api/me")
async def get_me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}
```

**Step 5: Run tests**
```bash
uv run pytest tests/test_auth.py -v
```
Expected: PASS

**Step 6: Commit**
```bash
git add apps/api/src/auth.py apps/api/src/main.py apps/api/tests/test_auth.py
git commit -m "feat: add Clerk JWT authentication middleware"
```

---

## Track C: Database Schema
**Depends on Track B (database.py). Run Week 1-2.**
**Owner: You or Claude**

### Task C1: Core data models

**Files:**
- Create: `apps/api/src/models/__init__.py`
- Create: `apps/api/src/models/organization.py`
- Create: `apps/api/src/models/team.py`
- Create: `apps/api/src/models/sprint.py`
- Create: `apps/api/src/models/ticket.py`
- Create: `apps/api/src/models/developer.py`
- Create: `apps/api/src/models/velocity.py`
- Create: `apps/api/alembic.ini`
- Create: `apps/api/alembic/env.py`

**Step 1: Create src/models/organization.py**
```python
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clerk_org_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # Encrypted Claude API key (BYOK)
    encrypted_anthropic_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Whether to use managed key (future: org pays us, we provide key)
    use_managed_key: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    teams: Mapped[list["Team"]] = relationship(back_populates="organization")
    jira_connections: Mapped[list["JiraConnection"]] = relationship(back_populates="organization")
```

**Step 2: Create src/models/team.py**
```python
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base

class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    jira_board_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    jira_project_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sprint_length_days: Mapped[int] = mapped_column(Integer, default=14)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="teams")
    sprints: Mapped[list["Sprint"]] = relationship(back_populates="team")
    members: Mapped[list["TeamMember"]] = relationship(back_populates="team")
```

**Step 3: Create src/models/sprint.py**
```python
import uuid
from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, ForeignKey, Float, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base
import enum

class SprintStatus(enum.Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class Sprint(Base):
    __tablename__ = "sprints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)
    jira_sprint_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[SprintStatus] = mapped_column(SAEnum(SprintStatus), default=SprintStatus.PLANNING)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Committed vs delivered (populated at sprint close)
    committed_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivered_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    spillover_points: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Sprint Brain AI output cached here
    ai_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0–1.0

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    team: Mapped["Team"] = relationship(back_populates="sprints")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="sprint")
```

**Step 4: Create src/models/ticket.py**
```python
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Float, Text, JSON, Enum as SAEnum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base
import enum

class TicketStatus(enum.Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"
    SPILLOVER = "spillover"

class SlipCause(enum.Enum):
    ESTIMATION = "estimation"
    DEPENDENCY = "dependency"
    SCOPE_CREEP = "scope_creep"
    QUALITY = "quality"
    BLOCKER = "blocker"
    UNKNOWN = "unknown"

class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sprint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sprints.id"), nullable=True, index=True)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("team_members.id"), nullable=True)
    jira_issue_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    jira_issue_key: Mapped[str | None] = mapped_column(String(50), nullable=True)

    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TicketStatus] = mapped_column(SAEnum(TicketStatus), default=TicketStatus.TODO)
    ticket_type: Mapped[str | None] = mapped_column(String(100), nullable=True)  # story, bug, task, spike
    story_points_estimated: Mapped[float | None] = mapped_column(Float, nullable=True)
    story_points_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_estimate_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_actual_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    labels: Mapped[list | None] = mapped_column(JSON, nullable=True)
    components: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Slip tracking
    did_spillover: Mapped[bool] = mapped_column(Boolean, default=False)
    slip_cause: Mapped[SlipCause | None] = mapped_column(SAEnum(SlipCause), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    jira_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sprint: Mapped["Sprint | None"] = relationship(back_populates="tickets")
    assignee: Mapped["TeamMember | None"] = relationship(back_populates="tickets")
```

**Step 5: Create src/models/developer.py**
```python
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base

class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)
    jira_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Capacity modifiers (default 1.0 = full capacity)
    default_capacity_factor: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    team: Mapped["Team"] = relationship(back_populates="members")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="assignee")
    velocity_records: Mapped[list["VelocityRecord"]] = relationship(back_populates="developer")
```

**Step 6: Create src/models/velocity.py**
```python
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base

class VelocityRecord(Base):
    """One record per developer per sprint, summarizing their performance."""
    __tablename__ = "velocity_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    developer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("team_members.id"), index=True)
    sprint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sprints.id"), index=True)

    points_committed: Mapped[float] = mapped_column(Float, default=0.0)
    points_delivered: Mapped[float] = mapped_column(Float, default=0.0)
    tickets_completed: Mapped[int] = mapped_column(default=0)
    tickets_spilled: Mapped[int] = mapped_column(default=0)

    # Breakdown by ticket type (JSON: {"story": 1.2, "bug": 0.8, "task": 1.0})
    avg_cycle_time_by_type: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Relative performance vs estimate (1.0 = on time, 1.5 = 50% over)
    estimation_ratio_by_type: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    developer: Mapped["TeamMember"] = relationship(back_populates="velocity_records")
    sprint: Mapped["Sprint"] = relationship()
```

**Step 7: Create Alembic migration**
```bash
cd apps/api
uv run alembic init alembic
# Edit alembic/env.py to import Base and use async engine
uv run alembic revision --autogenerate -m "initial schema"
uv run alembic upgrade head
```
Expected: all tables created in PostgreSQL. Verify: `psql -U agileos agileos -c "\dt"`

**Step 8: Commit**
```bash
git add apps/api/src/models/ apps/api/alembic/
git commit -m "feat: add core database models — org, team, sprint, ticket, developer, velocity"
```

---

## Track D: Jira Integration
**Depends on Track B + C. Run Week 1-2.**
**Owner: `jira-integration-agent`**

### Task D1: Jira OAuth2 connection flow

**Files:**
- Create: `apps/api/src/models/jira_connection.py`
- Create: `apps/api/src/integrations/jira/oauth.py`
- Create: `apps/api/src/integrations/jira/router.py`
- Modify: `apps/api/src/main.py`

**Step 1: Register Jira OAuth app**
> **🧑 HUMAN TASK:** Go to https://developer.atlassian.com/console/myapps/ → Create app → OAuth 2.0 (3LO) → Set redirect URI to `http://localhost:8000/api/integrations/jira/callback` → Copy Client ID and Client Secret to `.env`

**Step 2: Create src/models/jira_connection.py**
```python
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base

class JiraConnection(Base):
    __tablename__ = "jira_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    jira_cloud_id: Mapped[str] = mapped_column(String(255))
    jira_cloud_url: Mapped[str] = mapped_column(String(500))
    # Tokens stored encrypted
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scopes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="jira_connections")
```

**Step 3: Create src/integrations/jira/oauth.py**
```python
import httpx
import secrets
from src.config import settings

JIRA_AUTH_URL = "https://auth.atlassian.com/authorize"
JIRA_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
JIRA_SCOPES = "read:jira-work read:jira-user write:jira-work offline_access"
JIRA_ACCESSIBLE_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

def get_authorization_url(state: str) -> str:
    params = {
        "audience": "api.atlassian.com",
        "client_id": settings.jira_client_id,
        "scope": JIRA_SCOPES,
        "redirect_uri": settings.jira_redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{JIRA_AUTH_URL}?{query}"

async def exchange_code_for_tokens(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            JIRA_TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": settings.jira_client_id,
                "client_secret": settings.jira_client_secret,
                "code": code,
                "redirect_uri": settings.jira_redirect_uri,
            },
        )
        response.raise_for_status()
        return response.json()

async def get_accessible_resources(access_token: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            JIRA_ACCESSIBLE_RESOURCES_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()

async def refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            JIRA_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": settings.jira_client_id,
                "client_secret": settings.jira_client_secret,
                "refresh_token": refresh_token,
            },
        )
        response.raise_for_status()
        return response.json()
```

**Step 4: Create src/integrations/jira/router.py**
```python
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
import secrets
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth import get_current_user_id
from src.database import get_db
from src.integrations.jira.oauth import get_authorization_url, exchange_code_for_tokens, get_accessible_resources
from src.services.encryption import encrypt, decrypt
from src.models.jira_connection import JiraConnection
from src.config import settings

router = APIRouter(prefix="/api/integrations/jira", tags=["jira"])

# In-memory state store (use Redis in production)
_oauth_states: dict[str, str] = {}

@router.get("/connect")
async def jira_connect(user_id: str = Depends(get_current_user_id)):
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = user_id
    return {"auth_url": get_authorization_url(state)}

@router.get("/callback")
async def jira_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    user_id = _oauth_states.pop(state, None)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    tokens = await exchange_code_for_tokens(code)
    resources = await get_accessible_resources(tokens["access_token"])

    if not resources:
        raise HTTPException(status_code=400, detail="No accessible Jira sites found")

    resource = resources[0]  # Take first site; allow selection in future
    connection = JiraConnection(
        jira_cloud_id=resource["id"],
        jira_cloud_url=resource["url"],
        encrypted_access_token=encrypt(tokens["access_token"]),
        encrypted_refresh_token=encrypt(tokens.get("refresh_token", "")),
        scopes=tokens.get("scope", "").split(),
    )
    db.add(connection)
    await db.commit()

    return RedirectResponse(f"{settings.frontend_url}/onboarding/jira-connected")

@router.get("/status")
async def jira_status(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # Return whether org has active Jira connection
    # Implementation: query JiraConnection for org
    return {"connected": False}  # stub — fill in after org service exists
```

**Step 5: Create src/services/encryption.py**
```python
import base64
from cryptography.fernet import Fernet
from src.config import settings

def _get_fernet() -> Fernet:
    # Convert 32-byte hex key to Fernet-compatible 32-byte key
    key_bytes = bytes.fromhex(settings.encryption_key)
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)

def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()

def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
```

**Step 6: Add Jira migration and run**
```bash
uv run alembic revision --autogenerate -m "add jira connections table"
uv run alembic upgrade head
```

**Step 7: Commit**
```bash
git add apps/api/src/integrations/ apps/api/src/services/encryption.py
git commit -m "feat: add Jira OAuth2 connection flow with encrypted token storage"
```

---

### Task D2: Jira data sync (Celery jobs)
**Depends on D1.**
**Owner: `jira-integration-agent`**

**Files:**
- Create: `apps/api/src/integrations/jira/client.py`
- Create: `apps/api/src/integrations/jira/sync.py`
- Create: `apps/api/src/worker.py`

**Step 1: Create Jira API client**
```python
# src/integrations/jira/client.py
import httpx
from dataclasses import dataclass

@dataclass
class JiraClient:
    cloud_id: str
    access_token: str

    @property
    def base_url(self) -> str:
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/api/3"

    async def get_boards(self) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/agile/1.0/board",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json().get("values", [])

    async def get_sprints(self, board_id: str) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/agile/1.0/board/{board_id}/sprint",
                headers=self._headers(),
                params={"state": "active,closed", "maxResults": 50},
            )
            r.raise_for_status()
            return r.json().get("values", [])

    async def get_sprint_issues(self, sprint_id: str) -> list[dict]:
        issues = []
        start_at = 0
        while True:
            async with httpx.AsyncClient() as c:
                r = await c.get(
                    f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/agile/1.0/sprint/{sprint_id}/issue",
                    headers=self._headers(),
                    params={"startAt": start_at, "maxResults": 100,
                            "fields": "summary,status,assignee,story_points,issuetype,labels,components,timespent,timeoriginalestimate,created,updated,resolutiondate"},
                )
                r.raise_for_status()
                data = r.json()
                issues.extend(data.get("issues", []))
                if start_at + 100 >= data.get("total", 0):
                    break
                start_at += 100
        return issues

    async def get_users(self) -> list[dict]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self.base_url}/users/search",
                headers=self._headers(),
                params={"maxResults": 200, "accountType": "atlassian"},
            )
            r.raise_for_status()
            return r.json()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}
```

**Step 2: Create Celery worker**
```python
# src/worker.py
from celery import Celery
from src.config import settings

celery_app = Celery(
    "agile-os",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["src.integrations.jira.sync"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
```

**Step 3: Create sync tasks**
```python
# src/integrations/jira/sync.py
from src.worker import celery_app

@celery_app.task(bind=True, max_retries=3)
def sync_jira_team(self, team_id: str):
    """Full sync of all sprints and issues for a team from Jira."""
    # Implementation: pull connection from DB, init JiraClient, sync sprints+issues
    # This task is the entry point; jira-integration-agent fleshes out the full impl
    pass

@celery_app.task(bind=True, max_retries=3)
def sync_jira_sprint(self, sprint_id: str, jira_sprint_id: str):
    """Sync a single sprint's issues from Jira."""
    pass
```

**Step 4: Start Celery worker**
```bash
cd apps/api && uv run celery -A src.worker worker --loglevel=info
```
Expected: `celery@hostname ready.`

**Step 5: Commit**
```bash
git add apps/api/src/integrations/jira/ apps/api/src/worker.py
git commit -m "feat: add Jira API client and Celery sync job scaffolding"
```

---

## Track E: Velocity Engine
**Depends on Track C. Runs Week 2, parallel with D.**
**Owner: `velocity-engine-agent`**

### Task E1: Per-developer velocity calculator

**Files:**
- Create: `apps/api/src/services/velocity.py`
- Create: `apps/api/tests/test_velocity.py`

**Step 1: Write failing tests**
```python
# tests/test_velocity.py
import pytest
from src.services.velocity import calculate_developer_velocity, SprintCapacityModel

def test_velocity_requires_minimum_three_sprints():
    records = [{"points_delivered": 5.0, "points_committed": 8.0}]  # only 1 sprint
    result = calculate_developer_velocity(records)
    assert result["has_sufficient_data"] is False
    assert result["sprints_needed"] == 2

def test_velocity_calculates_mean_and_std():
    records = [
        {"points_delivered": 8.0, "points_committed": 10.0},
        {"points_delivered": 7.0, "points_committed": 9.0},
        {"points_delivered": 9.0, "points_committed": 10.0},
    ]
    result = calculate_developer_velocity(records)
    assert result["has_sufficient_data"] is True
    assert result["mean_velocity"] == pytest.approx(8.0, abs=0.1)
    assert result["confidence_capacity"] <= result["mean_velocity"]

def test_sprint_capacity_model_applies_pto():
    model = SprintCapacityModel(
        mean_velocity=8.0,
        std_dev=1.0,
        sprint_days=10,
        pto_days=2,
        meetings_hours_per_day=1.0,
    )
    capacity = model.recommended_capacity()
    assert capacity < 8.0  # PTO reduces capacity
```

**Step 2: Run tests to verify fail**
```bash
uv run pytest tests/test_velocity.py -v
```
Expected: ImportError — module doesn't exist

**Step 3: Create src/services/velocity.py**
```python
import statistics
from dataclasses import dataclass

def calculate_developer_velocity(sprint_records: list[dict]) -> dict:
    """
    Calculate a developer's velocity profile from historical sprint records.
    Returns mean, std dev, confidence interval, and whether there's enough data.
    """
    MIN_SPRINTS = 3
    if len(sprint_records) < MIN_SPRINTS:
        return {
            "has_sufficient_data": False,
            "sprints_needed": MIN_SPRINTS - len(sprint_records),
            "mean_velocity": None,
        }

    delivered = [r["points_delivered"] for r in sprint_records]
    mean = statistics.mean(delivered)
    std = statistics.stdev(delivered) if len(delivered) > 1 else 0.0

    # Conservative capacity: mean - 0.5 * std_dev (roughly 70th percentile safe)
    confidence_capacity = max(0.0, mean - (0.5 * std))

    return {
        "has_sufficient_data": True,
        "mean_velocity": round(mean, 2),
        "std_dev": round(std, 2),
        "confidence_capacity": round(confidence_capacity, 2),
        "sprint_count": len(sprint_records),
        "min_observed": min(delivered),
        "max_observed": max(delivered),
    }

@dataclass
class SprintCapacityModel:
    mean_velocity: float
    std_dev: float
    sprint_days: int
    pto_days: float = 0.0
    meetings_hours_per_day: float = 0.0
    part_time_factor: float = 1.0  # 0.5 = half time

    def recommended_capacity(self) -> float:
        """Return recommended story points to commit for this developer this sprint."""
        available_days = (self.sprint_days - self.pto_days) * self.part_time_factor
        meeting_overhead = (self.meetings_hours_per_day * available_days) / 8.0
        effective_days_ratio = (available_days - meeting_overhead) / self.sprint_days

        # Scale confidence_capacity by availability ratio
        base = max(0.0, self.mean_velocity - (0.5 * self.std_dev))
        return round(base * effective_days_ratio, 1)
```

**Step 4: Run tests to verify pass**
```bash
uv run pytest tests/test_velocity.py -v
```
Expected: 3 PASS

**Step 5: Commit**
```bash
git add apps/api/src/services/velocity.py apps/api/tests/test_velocity.py
git commit -m "feat: add per-developer velocity calculator with sprint capacity model"
```

---

### Task E2: Velocity API endpoints

**Files:**
- Create: `apps/api/src/routers/velocity.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.auth import get_current_user_id
from src.database import get_db
from src.models.velocity import VelocityRecord
from src.models.developer import TeamMember
from src.services.velocity import calculate_developer_velocity

router = APIRouter(prefix="/api/teams/{team_id}/velocity", tags=["velocity"])

@router.get("/")
async def get_team_velocity(
    team_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return velocity profiles for all developers on a team."""
    members_result = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.is_active == True)
    )
    members = members_result.scalars().all()

    profiles = []
    for member in members:
        records_result = await db.execute(
            select(VelocityRecord)
            .where(VelocityRecord.developer_id == member.id)
            .order_by(VelocityRecord.created_at.desc())
            .limit(10)
        )
        records = records_result.scalars().all()
        velocity = calculate_developer_velocity([
            {"points_delivered": r.points_delivered, "points_committed": r.points_committed}
            for r in records
        ])
        profiles.append({
            "developer_id": str(member.id),
            "display_name": member.display_name,
            "velocity": velocity,
        })

    return {"team_id": team_id, "profiles": profiles}
```

---

## Track F: Sprint Brain AI Interface (BYOK)
**Depends on Track B + C + E. Run Week 2-3.**
**Owner: YOU — this is your agentic AI learning track**

> ⚠️ **This is your learning track.** The scaffolding below defines the contracts. You fill in the Claude API calls, prompts, and agentic logic.

### Task F1: BYOK key management

**Files:**
- Create: `apps/api/src/routers/settings.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from src.auth import get_current_user_id
from src.database import get_db
from src.services.encryption import encrypt, decrypt
from src.models.organization import Organization
from sqlalchemy import select

router = APIRouter(prefix="/api/settings", tags=["settings"])

class AnthropicKeyPayload(BaseModel):
    api_key: str  # Raw key from user — never logged, immediately encrypted

@router.post("/anthropic-key")
async def save_anthropic_key(
    payload: AnthropicKeyPayload,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Store customer's Anthropic API key, encrypted at rest."""
    # TODO: get org from user_id, update encrypted_anthropic_key
    encrypted = encrypt(payload.api_key)
    return {"saved": True}

@router.get("/anthropic-key/status")
async def anthropic_key_status(user_id: str = Depends(get_current_user_id)):
    """Return whether org has an Anthropic key saved (not the key itself)."""
    return {"has_key": False}  # stub
```

### Task F2: Sprint Brain AI service interface

**Files:**
- Create: `apps/api/src/services/sprint_brain.py`

```python
# THIS FILE IS YOUR AGENTIC AI LEARNING SURFACE.
# The interface is defined here. You implement the AI logic inside.
from dataclasses import dataclass
from typing import Any
import anthropic

@dataclass
class SprintBrainInput:
    team_id: str
    candidate_tickets: list[dict]      # List of ticket dicts from backlog
    developer_profiles: list[dict]     # Output from velocity engine
    sprint_length_days: int
    sprint_start_date: str
    pto_overrides: dict[str, float]    # developer_id -> pto_days this sprint

@dataclass
class SprintBrainOutput:
    assignments: list[dict]            # [{ticket_id, developer_id, reasoning, confidence}]
    confidence_score: float            # 0.0–1.0 overall sprint confidence
    summary: str                       # Natural language summary of the plan
    warnings: list[str]                # Risk flags to surface to the user
    what_if_dropped: dict[str, float]  # ticket_id -> new_confidence if dropped

async def generate_sprint_plan(
    input: SprintBrainInput,
    anthropic_api_key: str,
) -> SprintBrainOutput:
    """
    YOUR TASK: Implement this using the Claude API.

    Recommended approach:
    1. Build a structured prompt from SprintBrainInput
    2. Call Claude claude-sonnet-4-6 with tool_use for structured output
    3. Parse and validate the response into SprintBrainOutput
    4. Handle rate limits, token limits, and API errors gracefully

    The Claude API key comes from the customer (BYOK) — never from env.
    Model to use: claude-sonnet-4-6 (good balance of quality + speed + cost)
    """
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    # TODO: Your implementation here
    raise NotImplementedError("Sprint Brain AI not yet implemented — your track!")
```

### Task F3: Sprint Brain API endpoint

**Files:**
- Create: `apps/api/src/routers/sprint_brain.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth import get_current_user_id
from src.database import get_db
from src.services.sprint_brain import generate_sprint_plan, SprintBrainInput
from src.services.encryption import decrypt
from pydantic import BaseModel

router = APIRouter(prefix="/api/sprint-brain", tags=["sprint-brain"])

class PlanRequest(BaseModel):
    team_id: str
    sprint_length_days: int = 14
    pto_overrides: dict[str, float] = {}

@router.post("/plan")
async def create_sprint_plan(
    request: PlanRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # 1. Get org's encrypted Anthropic key
    # 2. Fetch candidate tickets and developer profiles
    # 3. Call generate_sprint_plan()
    # 4. Return structured plan
    raise HTTPException(status_code=501, detail="Set your Anthropic API key first")
```

**Step: Commit**
```bash
git add apps/api/src/services/sprint_brain.py apps/api/src/routers/
git commit -m "feat: define Sprint Brain AI interface contracts (BYOK, your implementation track)"
```

---

## Track G: React Web App Scaffold
**Independent. Run Week 1, parallel with everything.**
**Owner: `dashboard-builder-agent`**

### Task G1: Create web app in monorepo

**Step 1: Scaffold**
```bash
cd apps
pnpm create vite@latest web -- --template react-ts
cd web && pnpm install
pnpm add @clerk/clerk-react @tanstack/react-query react-router-dom recharts
pnpm add -D @types/react @types/react-dom
```

**Step 2: Create apps/web/src/main.tsx**
```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ClerkProvider } from '@clerk/clerk-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

const queryClient = new QueryClient()
const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ClerkProvider>
  </StrictMode>
)
```

**Step 3: Create apps/web/src/App.tsx with routing**
```tsx
import { Routes, Route, Navigate } from 'react-router-dom'
import { SignedIn, SignedOut, RedirectToSignIn } from '@clerk/clerk-react'
import { DashboardLayout } from './layouts/DashboardLayout'
import { SprintPlannerPage } from './pages/SprintPlannerPage'
import { VelocityMirrorPage } from './pages/VelocityMirrorPage'
import { OnboardingPage } from './pages/OnboardingPage'
import { SettingsPage } from './pages/SettingsPage'

export default function App() {
  return (
    <Routes>
      <Route path="/sign-in/*" element={<SignInPage />} />
      <Route path="/onboarding/*" element={
        <SignedIn><OnboardingPage /></SignedIn>
      } />
      <Route path="/app" element={
        <>
          <SignedIn>
            <DashboardLayout />
          </SignedIn>
          <SignedOut>
            <RedirectToSignIn />
          </SignedOut>
        </>
      }>
        <Route index element={<Navigate to="sprint-planner" replace />} />
        <Route path="sprint-planner" element={<SprintPlannerPage />} />
        <Route path="velocity-mirror" element={<VelocityMirrorPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  )
}
```

**Step 4: Create api client utility**
```typescript
// src/lib/api.ts
import { useAuth } from '@clerk/clerk-react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export function useApi() {
  const { getToken } = useAuth()

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const token = await getToken()
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        ...options.headers,
      },
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || `API error ${response.status}`)
    }
    return response.json()
  }

  return { get: <T>(path: string) => request<T>(path),
           post: <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }) }
}
```

**Step 5: Verify dev server**
```bash
cd apps/web && pnpm dev --port 5174
```
Expected: `Local: http://localhost:5174/`

**Step 6: Commit**
```bash
git add apps/web/
git commit -m "feat: scaffold React web app with Clerk auth, TanStack Query, routing"
```

---

## Track H: Sprint Brain UI
**Depends on Track F (API endpoints) + Track G. Run Week 3-4.**
**Owner: `dashboard-builder-agent`**

### Task H1: Jira connection onboarding flow

**Files:**
- Create: `apps/web/src/pages/OnboardingPage.tsx`
- Create: `apps/web/src/pages/onboarding/ConnectJiraStep.tsx`
- Create: `apps/web/src/pages/onboarding/SaveAnthropicKeyStep.tsx`
- Create: `apps/web/src/pages/onboarding/SelectBoardStep.tsx`

The onboarding flow is 3 steps:
1. Connect Jira (redirects to Atlassian OAuth)
2. Select board + project
3. Save Anthropic API key (with link to get one)

**Key interaction for SaveAnthropicKeyStep:**
```tsx
// User pastes their Anthropic key — we POST to /api/settings/anthropic-key
// Show masked display (sk-ant-...xxxx) after save
// Link to https://console.anthropic.com to get a key
```

### Task H2: Sprint planning wizard

**Files:**
- Create: `apps/web/src/pages/SprintPlannerPage.tsx`
- Create: `apps/web/src/components/sprint/VelocityCard.tsx`
- Create: `apps/web/src/components/sprint/TicketList.tsx`
- Create: `apps/web/src/components/sprint/ConfidenceGauge.tsx`
- Create: `apps/web/src/components/sprint/PlanReasoningPanel.tsx`

**VelocityCard spec:**
- Shows developer name, avatar initial, mean velocity, confidence capacity
- Bar showing committed vs capacity
- "Insufficient data" state for < 3 sprints (shows number of sprints needed)
- Green/amber/red colour based on utilisation

**ConfidenceGauge spec:**
- Radial gauge 0–100%
- Green > 75%, amber 50–75%, red < 50%
- Animated fill on load
- Tooltip: "Based on N sprints of historical data"

**PlanReasoningPanel spec:**
- List of assignments with reasoning text
- "Why this assignment?" expandable per ticket
- Warning chips for any flagged risks

**Step: Commit after each component**
```bash
git commit -m "feat: add VelocityCard component"
git commit -m "feat: add sprint planning wizard with confidence gauge"
```

---

## Track I: Velocity Mirror UI (Live Dashboard)
**Depends on Track G + data flowing from Track D. Run Week 4.**
**Owner: `dashboard-builder-agent`**

### Task I1: Live burndown chart

**Files:**
- Create: `apps/web/src/pages/VelocityMirrorPage.tsx`
- Create: `apps/web/src/components/mirror/BurndownChart.tsx`
- Create: `apps/web/src/components/mirror/DeveloperCapacityRow.tsx`
- Create: `apps/web/src/components/mirror/AlertFeed.tsx`
- Create: `apps/web/src/components/mirror/SprintHealthScore.tsx`

**BurndownChart spec:**
- Area chart (Recharts AreaChart)
- X-axis: sprint days, Y-axis: story points remaining
- Three lines: ideal burndown (straight line from committed to 0), actual, AI-predicted end point
- If predicted end > sprint end date, show red zone

**SprintHealthScore spec:**
- Large number badge (0–100)
- Colour coded: green/amber/red
- Below: 3 bullet "why" statements from the AI assessment
- Updates every 5 minutes via polling (`refetchInterval: 300000` in TanStack Query)

**AlertFeed spec:**
- Chronological list of alerts
- Alert types: stalled ticket, over-capacity developer, dependency risk, spillover prediction
- Each alert has: icon, description, recommended action, dismiss button

**Step: Commit**
```bash
git add apps/web/src/pages/VelocityMirrorPage.tsx apps/web/src/components/mirror/
git commit -m "feat: add Velocity Mirror live dashboard with burndown, capacity, and alerts"
```

---

## Track J: Launch Preparation
**Depends on all tracks. Run Week 5-6.**
**Owner: You**

### Task J1: Stripe billing integration

> **🧑 HUMAN TASK:** Create Stripe account → create 3 products (Starter $99, Growth $299, Enterprise custom) → save `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` to `.env`

**Files:**
- Create: `apps/api/src/routers/billing.py`

```python
import stripe
from fastapi import APIRouter, Request, HTTPException
from src.config import settings

stripe.api_key = settings.stripe_secret_key

router = APIRouter(prefix="/api/billing", tags=["billing"])

PRICE_IDS = {
    "starter": "price_xxx",   # $99/month — fill in from Stripe
    "growth": "price_xxx",    # $299/month
}

@router.post("/checkout")
async def create_checkout_session(plan: str):
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": PRICE_IDS[plan], "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.frontend_url}/app?subscribed=true",
        cancel_url=f"{settings.frontend_url}/pricing",
    )
    return {"checkout_url": session.url}
```

### Task J2: Error monitoring

**Step 1: Add Sentry**
```bash
cd apps/api && uv add sentry-sdk
cd apps/web && pnpm add @sentry/react
```

**Step 2: Initialize in main.py**
```python
import sentry_sdk
sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)
```

### Task J3: Deploy to Railway + Vercel

**Step 1: Create Railway project**
- New project → deploy from GitHub → add PostgreSQL and Redis services
- Set all env vars from `.env.example`

**Step 2: Create `apps/api/Dockerfile`**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY src/ ./src/
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Deploy frontend to Vercel**
```bash
cd apps/web && npx vercel --prod
```
Set env vars: `VITE_CLERK_PUBLISHABLE_KEY`, `VITE_API_URL`

**Step 4: Smoke test production**
- [ ] Sign up flow works
- [ ] Jira OAuth connects
- [ ] Anthropic key saves
- [ ] Sprint plan generates
- [ ] Velocity Mirror loads

**Step 5: Commit and tag**
```bash
git tag -a v0.1.0-beta -m "AgileOS MVP beta release"
git push origin main --tags
```

---

## Execution Options

Plan complete and saved to `docs/plans/2026-03-09-agile-os-mvp.md`.

**1. Subagent-Driven (this session)** — Fresh subagent per task, review between tasks, fast iteration. Use `superpowers:subagent-driven-development`.

**2. Parallel Session (separate)** — Open new session, use `superpowers:executing-plans`, batch execution with checkpoints.

**Which approach?**
