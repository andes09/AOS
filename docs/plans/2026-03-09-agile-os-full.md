# AgileOS Full Product Implementation Plan (All 5 Modules)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> **Prerequisite:** The MVP plan (`2026-03-09-agile-os-mvp.md`) must be complete before starting Month 3 tracks.

**Goal:** Ship the complete AgileOS platform — all 5 modules, 3 integrations, enterprise billing, and a continuous learning loop — within 3–5 months of the MVP launch.

**Architecture:** Extends the MVP monorepo. New modules add to existing FastAPI backend and React web app. No new services needed until enterprise scale.

**Tech Stack:** Same as MVP + Linear GraphQL API, GitHub REST API, Slack API, Confluence/Notion write APIs, Google Calendar API.

---

## ⚠️ My Opinions & Pushback

**On module order:** The PRD GTM plan says Scope Cop + Dependency Radar in Month 7-9. I'm moving them earlier (Month 3-4) because they share the same ticket/sprint data models already built in the MVP. The engineering cost is low; the value-add is high. Retrospective AI comes last because it needs the most historical data to shine.

**On the "AI tool" positioning risk:** The PRD correctly calls this out. When building Scope Cop and Retrospective AI, never surface the word "AI" in the UI. Use "Sprint Intelligence," "Scope Analysis," "Automated Retrospective Report." The AI is the engine, not the product.

**On per-developer data visibility (Open Question from PRD):** My recommendation — individual velocity data is visible to the developer themselves and to their direct manager only, never to peers. Admin can configure this. Build this permission model in Month 3 before you have paying enterprise customers asking for it.

**On non-software markets (hardware, manufacturing):** Don't pursue in Year 1. The Jira/Linear integrations are software-specific. The positioning is software-specific. Expanding dilutes your ICP before you have PMF. Revisit in Year 2.

---

## 🤖 Additional Proposed Agents (beyond MVP agents)

### Agent: `scope-cop-agent`
**Purpose:** Implements the Scope Cop module — ticket quality analysis, scope ambiguity detection, and split suggestions.
**Skills to give it:**
- Text similarity and embedding comparison (for comparing new tickets to historical ones)
- Anthropic Claude API for natural language ticket analysis
- FastAPI route implementation
- Jira/Linear webhook handlers for real-time ticket analysis
- Acceptance criteria template generation
- Story point anomaly detection using historical velocity data

### Agent: `dependency-radar-agent`
**Purpose:** Builds Dependency Radar — reliability scoring, sprint risk reports, and automated stakeholder nudges.
**Skills to give it:**
- Graph data structures for dependency relationship modelling
- Reliability score calculation (on-time delivery ratio with recency weighting)
- Slack API for automated nudge messages
- Risk report generation with Claude API
- SQLAlchemy models for dependency tracking
- Notification scheduling with Celery Beat

### Agent: `retrospective-ai-agent`
**Purpose:** Builds the Retrospective AI module — automated sprint reports, pattern detection, and action item tracking.
**Skills to give it:**
- Cross-sprint pattern analysis (comparing slip causes across sprints)
- Claude API for generating natural language retrospective reports
- Action item extraction and tracking
- Confluence and Notion write APIs for report export
- Team Health Score calculation
- Trend visualization data preparation

### Agent: `linear-github-integration-agent`
**Purpose:** Adds Linear (GraphQL) and GitHub Projects (REST) integrations alongside the existing Jira integration.
**Skills to give it:**
- Linear GraphQL API (cycles = sprints, issues, team members)
- GitHub Projects REST API v2 (project items, iterations)
- OAuth2 flows for both platforms
- Data normalization to AgileOS internal schema (same models as Jira sync)
- Celery sync tasks using same pattern as Jira integration

### Agent: `enterprise-features-agent`
**Purpose:** Adds SSO, admin controls, audit logs, and multi-team management for enterprise customers.
**Skills to give it:**
- SAML/OIDC SSO implementation with Clerk Organizations
- Role-based access control (RBAC) with FastAPI dependencies
- Audit log design and implementation
- Admin dashboard UI with React
- Multi-team hierarchy (org → department → team)
- Data export (CSV, JSON) implementation

---

## Parallel Execution Map

```
Month 1-2:  MVP Plan (see agile-os-mvp.md)
                ↓
Month 3:    [Track K: Scope Cop]  [Track L: Linear Integration]  [Track M: Permission Model]
Month 3-4:  [Track N: Dependency Radar]
Month 4:    [Track O: GitHub Projects Integration]  [Track P: Slack Notifications]
Month 4-5:  [Track Q: Retrospective AI]
Month 5:    [Track R: Enterprise Features]  [Track S: Team Health Score]
```

---

## Track K: Scope Cop — Ticket Quality Enforcer
**Depends on MVP complete. Run Month 3.**
**Owner: `scope-cop-agent`**
**AI portions: YOU (agentic AI learning track)**

### Task K1: Scope Cop data model

**Files:**
- Create: `apps/api/src/models/scope_analysis.py`

```python
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Float, JSON, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base

class ScopeAnalysis(Base):
    """Result of Scope Cop analysis for a single ticket."""
    __tablename__ = "scope_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id"), index=True)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id"), index=True)

    # Scores (0.0–1.0, higher = healthier)
    clarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimation_reliability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    acceptance_criteria_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_health_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Flags
    should_split: Mapped[bool] = mapped_column(Boolean, default=False)
    split_suggestions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    missing_criteria: Mapped[list | None] = mapped_column(JSON, nullable=True)
    similar_tickets: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ticket IDs + similarity scores

    # Raw AI output
    analysis_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

**Step: Run migration**
```bash
cd apps/api && uv run alembic revision --autogenerate -m "add scope analyses table"
uv run alembic upgrade head
```

**Step: Commit**
```bash
git add apps/api/src/models/scope_analysis.py
git commit -m "feat: add ScopeAnalysis model for Scope Cop module"
```

---

### Task K2: Scope Cop AI service interface

**Files:**
- Create: `apps/api/src/services/scope_cop.py`

```python
# YOUR AGENTIC AI LEARNING SURFACE — implement the AI logic here.
from dataclasses import dataclass
import anthropic

@dataclass
class ScopeCopInput:
    ticket_title: str
    ticket_description: str
    acceptance_criteria: str
    story_points_estimated: float | None
    ticket_type: str
    team_id: str
    similar_historical_tickets: list[dict]  # pre-fetched by the caller

@dataclass
class ScopeCopOutput:
    overall_health_score: float         # 0.0–1.0
    clarity_score: float
    estimation_reliability_score: float
    acceptance_criteria_score: float
    should_split: bool
    split_suggestions: list[str]        # Natural language split recommendations
    missing_criteria: list[str]         # What acceptance criteria are missing
    warnings: list[str]                 # Human-readable warnings for PM/dev
    analysis_summary: str               # 2–3 sentence summary

async def analyse_ticket(
    input: ScopeCopInput,
    anthropic_api_key: str,
) -> ScopeCopOutput:
    """
    YOUR TASK: Analyse a ticket for quality issues using Claude.

    Recommended approach:
    1. Construct a prompt that includes the ticket + historical similar tickets
    2. Ask Claude to identify: clarity issues, scope ambiguity, missing criteria
    3. Use tool_use / structured output to get consistent JSON back
    4. Map to ScopeCopOutput

    Agentic enhancement opportunity: Use multi-turn conversation to
    interactively refine the analysis when the ticket description is very short.
    """
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    raise NotImplementedError("Scope Cop AI — your implementation track")
```

---

### Task K3: Scope Cop Jira webhook handler

**Files:**
- Create: `apps/api/src/integrations/jira/webhooks.py`
- Modify: `apps/api/src/integrations/jira/router.py`

```python
# webhooks.py — triggered when a ticket is created or updated in Jira
from fastapi import APIRouter, Request, BackgroundTasks
from src.services.scope_cop import analyse_ticket, ScopeCopInput
from src.worker import celery_app

webhook_router = APIRouter(prefix="/api/webhooks/jira")

@webhook_router.post("/issue")
async def jira_issue_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Receive Jira webhook for issue created/updated events."""
    payload = await request.json()
    event_type = payload.get("webhookEvent", "")

    if event_type in ("jira:issue_created", "jira:issue_updated"):
        issue_key = payload["issue"]["key"]
        # Queue background Scope Cop analysis
        background_tasks.add_task(run_scope_cop_for_issue, issue_key)

    return {"received": True}

async def run_scope_cop_for_issue(issue_key: str):
    """Background task: fetch ticket from DB, run Scope Cop, save result."""
    # 1. Look up ticket by jira_issue_key
    # 2. Fetch org's Anthropic key
    # 3. Fetch similar historical tickets (top 5 by title similarity)
    # 4. Call analyse_ticket()
    # 5. Save ScopeAnalysis to DB
    pass  # scope-cop-agent implements this
```

---

### Task K4: Scope Cop UI — Ticket health widget

**Files:**
- Create: `apps/web/src/components/scope/TicketHealthBadge.tsx`
- Create: `apps/web/src/components/scope/ScopeAnalysisPanel.tsx`
- Create: `apps/web/src/pages/BacklogHealthPage.tsx`

**TicketHealthBadge spec:**
- Small chip showing overall health score with colour (green/amber/red)
- Click to expand ScopeAnalysisPanel
- Appears inline in the sprint planning wizard ticket list

**ScopeAnalysisPanel spec:**
- Full analysis breakdown: clarity, estimation, acceptance criteria scores
- Split suggestions as an expandable list
- "Generate acceptance criteria" button → calls AI endpoint
- Missing criteria list with checkboxes

**BacklogHealthPage spec:**
- Table of all backlog tickets sorted by health score (lowest first)
- Aggregate backlog health score at top
- "Fix all low-quality tickets" batch AI action button

**Step: Commit**
```bash
git add apps/web/src/components/scope/ apps/web/src/pages/BacklogHealthPage.tsx
git commit -m "feat: add Scope Cop UI components — ticket health badge and backlog health page"
```

---

## Track L: Linear Integration
**Independent of K. Run Month 3 parallel with K.**
**Owner: `linear-github-integration-agent`**

### Task L1: Linear OAuth + GraphQL client

**Files:**
- Create: `apps/api/src/models/linear_connection.py`
- Create: `apps/api/src/integrations/linear/oauth.py`
- Create: `apps/api/src/integrations/linear/client.py`
- Create: `apps/api/src/integrations/linear/sync.py`

**Linear OAuth Setup:**
> **🧑 HUMAN TASK:** Go to Linear Settings → API → OAuth applications → Create app → Set redirect URI → Copy credentials to `.env`

**Linear client key methods to implement:**
```python
class LinearClient:
    async def get_teams(self) -> list[dict]: ...          # teams { id name }
    async def get_cycles(self, team_id: str) -> list[dict]: ...  # cycles (= sprints)
    async def get_cycle_issues(self, cycle_id: str) -> list[dict]: ...  # issues in cycle
    async def get_members(self, team_id: str) -> list[dict]: ...
```

**Data normalization principle:** Map Linear's concept names to AgileOS internal schema:
- Linear `Cycle` → AgileOS `Sprint`
- Linear `Issue` → AgileOS `Ticket`
- Linear `Team` → AgileOS `Team`
- Linear `Member` → AgileOS `TeamMember`

**Step: Commit after each file**
```bash
git commit -m "feat: add Linear OAuth2 and GraphQL integration"
git commit -m "feat: add Linear data sync to internal schema"
```

---

## Track M: Permission Model
**Depends on MVP. Run Month 3 (critical before enterprise).**
**Owner: You or Claude**

### Task M1: Role-based access control

**Files:**
- Create: `apps/api/src/models/membership.py`
- Create: `apps/api/src/services/permissions.py`
- Modify: `apps/api/src/auth.py`

```python
# models/membership.py
import enum

class OrgRole(enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"     # Can see all team data including individual velocity
    MEMBER = "member"       # Can see own velocity only, not peers'
    VIEWER = "viewer"       # Read-only, no individual data

class OrgMembership(Base):
    __tablename__ = "org_memberships"
    id: Mapped[uuid.UUID] = mapped_column(...)
    organization_id: Mapped[uuid.UUID] = mapped_column(...)
    clerk_user_id: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[OrgRole] = mapped_column(SAEnum(OrgRole))
    created_at: Mapped[datetime] = mapped_column(...)
```

```python
# services/permissions.py
def can_view_individual_velocity(requester_role: OrgRole, target_user_id: str, requester_user_id: str) -> bool:
    """
    MEMBER can only see their own velocity.
    MANAGER+ can see all team members' velocity.
    """
    if requester_role in (OrgRole.OWNER, OrgRole.ADMIN, OrgRole.MANAGER):
        return True
    return target_user_id == requester_user_id
```

**Step: Migration + commit**
```bash
uv run alembic revision --autogenerate -m "add org memberships and RBAC"
git commit -m "feat: add role-based access control for per-developer data visibility"
```

---

## Track N: Dependency Radar
**Depends on MVP + Track M. Run Month 3-4.**
**Owner: `dependency-radar-agent`**
**AI portions: YOU (agentic AI learning track)**

### Task N1: Dependency data model

**Files:**
- Create: `apps/api/src/models/dependency.py`

```python
class DependencySource(Base):
    """An external team, supplier, or stakeholder that the team depends on."""
    __tablename__ = "dependency_sources"

    id: Mapped[uuid.UUID] = ...
    organization_id: Mapped[uuid.UUID] = ...
    name: Mapped[str] = mapped_column(String(255))
    contact_email: Mapped[str | None] = ...
    source_type: Mapped[str] = ...  # "internal_team", "supplier", "stakeholder"
    slack_user_id: Mapped[str | None] = ...  # for automated nudges

class DependencyRecord(Base):
    """One record per sprint per dependency source — was it delivered on time?"""
    __tablename__ = "dependency_records"

    id: Mapped[uuid.UUID] = ...
    sprint_id: Mapped[uuid.UUID] = ...
    source_id: Mapped[uuid.UUID] = ...
    ticket_id: Mapped[uuid.UUID | None] = ...  # blocking ticket, if any
    was_blocking: Mapped[bool] = ...            # did a sprint ticket depend on this?
    committed_delivery_date: Mapped[date | None] = ...
    actual_delivery_date: Mapped[date | None] = ...
    delivered_on_time: Mapped[bool | None] = ...  # null = not yet resolved
    notes: Mapped[str | None] = ...
```

### Task N2: Reliability score calculator

**Files:**
- Create: `apps/api/src/services/dependency_reliability.py`
- Create: `apps/api/tests/test_dependency_reliability.py`

```python
# Test-first
def test_reliability_score_with_all_on_time():
    records = [{"delivered_on_time": True}] * 6
    assert calculate_reliability_score(records) == pytest.approx(1.0, abs=0.01)

def test_reliability_score_with_poor_track_record():
    records = [
        {"delivered_on_time": True},
        {"delivered_on_time": True},
        {"delivered_on_time": False},
        {"delivered_on_time": False},
        {"delivered_on_time": False},
        {"delivered_on_time": False},
    ]
    score = calculate_reliability_score(records)
    assert score < 0.4  # 2/6 on time

def test_recent_failures_weighted_more():
    # Most recent 3 all failures, oldest 3 all success
    records = [
        {"delivered_on_time": True, "recency_weight": 0.5},
        {"delivered_on_time": True, "recency_weight": 0.5},
        {"delivered_on_time": True, "recency_weight": 0.5},
        {"delivered_on_time": False, "recency_weight": 1.5},
        {"delivered_on_time": False, "recency_weight": 1.5},
        {"delivered_on_time": False, "recency_weight": 1.5},
    ]
    score = calculate_reliability_score(records)
    assert score < 0.4  # recent failures dominate
```

```python
# Implementation
def calculate_reliability_score(records: list[dict]) -> float:
    """
    Weighted reliability score: recent sprints weighted 1.5x, older 0.5x.
    Returns 0.0–1.0.
    """
    if not records:
        return 1.0  # No data — assume reliable (optimistic default)

    total_weight = 0.0
    weighted_success = 0.0
    n = len(records)

    for i, record in enumerate(records):
        # More recent = higher weight. Linear decay.
        weight = 0.5 + (i / max(n - 1, 1))  # 0.5 for oldest, 1.5 for newest
        total_weight += weight
        if record.get("delivered_on_time"):
            weighted_success += weight

    return round(weighted_success / total_weight, 3)
```

### Task N3: Sprint risk report AI service

**Files:**
- Create: `apps/api/src/services/dependency_risk.py`

```python
# YOUR AGENTIC AI LEARNING SURFACE
async def generate_sprint_risk_report(
    sprint_id: str,
    dependency_sources_with_scores: list[dict],
    tickets_blocked_by_deps: list[dict],
    anthropic_api_key: str,
) -> dict:
    """
    YOUR TASK: Generate a natural-language sprint risk report.

    Output should include:
    - Summary: "Your sprint has N high-risk dependencies"
    - Per-dependency risk assessment with reliability score shown
    - Contingency plan: what to do if each high-risk dep fails
    - Recommended: which tickets to have fallback tasks for

    Agentic enhancement opportunity: structured multi-step reasoning —
    first identify risks, then generate contingency plans as a separate step.
    """
    raise NotImplementedError("Dependency risk report — your implementation track")
```

### Task N4: Dependency Radar UI

**Files:**
- Create: `apps/web/src/pages/DependencyRadarPage.tsx`
- Create: `apps/web/src/components/dependencies/DependencyMap.tsx`
- Create: `apps/web/src/components/dependencies/ReliabilityScorecard.tsx`
- Create: `apps/web/src/components/dependencies/SprintRiskReport.tsx`

**DependencyMap spec:**
- Table (not a graph) of all dependencies for current sprint
- Columns: Source name, reliability score (coloured badge), sprints tracked, blocking tickets count
- Sort by reliability score ascending (worst first)

**ReliabilityScorecard spec:**
- Click into any dependency source
- Show sprint-by-sprint on-time record (green/red dots)
- Rolling 6-sprint trend line
- "Send nudge" button → triggers Slack message if configured

**SprintRiskReport spec:**
- AI-generated report shown at top of page before sprint starts
- "High risk" / "Medium risk" / "Low risk" section headers
- Contingency plan per risk
- "Acknowledge risks and proceed" CTA button to dismiss

---

## Track O: GitHub Projects Integration
**Independent. Run Month 4, parallel with N.**
**Owner: `linear-github-integration-agent`**

### Task O1: GitHub Projects OAuth + REST client

**Files:**
- Create: `apps/api/src/integrations/github/oauth.py`
- Create: `apps/api/src/integrations/github/client.py`
- Create: `apps/api/src/integrations/github/sync.py`

**Key GitHub Projects API methods:**
```python
class GitHubProjectsClient:
    async def get_projects(self, org: str) -> list[dict]: ...     # list projects
    async def get_project_items(self, project_id: str) -> list[dict]: ...  # issues/PRs
    async def get_iterations(self, project_id: str) -> list[dict]: ...  # = sprints
```

**Note:** GitHub Projects V2 uses GraphQL. Use the `gql` Python library.

> **🧑 HUMAN TASK:** Create GitHub OAuth App at github.com/settings/developers → Set callback URL → Add `GITHUB_CLIENT_ID` + `GITHUB_CLIENT_SECRET` to `.env`

---

## Track P: Slack Notifications
**Depends on MVP deploy. Run Month 4.**
**Owner: You or `dependency-radar-agent`**

### Task P1: Slack app setup and webhook handler

**Files:**
- Create: `apps/api/src/integrations/slack/client.py`
- Create: `apps/api/src/integrations/slack/router.py`

> **🧑 HUMAN TASK:** Create Slack app at api.slack.com/apps → Add `chat:write` and `incoming-webhook` scopes → Add Bot Token to `.env` as `SLACK_BOT_TOKEN`

```python
# client.py
import httpx

class SlackClient:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token

    async def send_message(self, channel: str, text: str, blocks: list | None = None):
        async with httpx.AsyncClient() as c:
            r = await c.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {self.bot_token}"},
                json={"channel": channel, "text": text, "blocks": blocks or []},
            )
            r.raise_for_status()

    async def send_dependency_nudge(self, slack_user_id: str, dependency_name: str, sprint_name: str, blocking_tickets: list[str]):
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"👋 Hi! Your delivery of *{dependency_name}* is on the critical path for *{sprint_name}*.\n\nBlocking: {', '.join(blocking_tickets)}"}},
            {"type": "section", "text": {"type": "mrkdwn",
                "text": "Can you confirm your delivery timeline? The team is counting on you. 🙏"}},
        ]
        await self.send_message(f"@{slack_user_id}", "", blocks)
```

**Celery Beat schedule for nudges:**
```python
# In worker.py celery config
celery_app.conf.beat_schedule = {
    "send-dependency-nudges-daily": {
        "task": "src.integrations.slack.tasks.send_dependency_nudges",
        "schedule": crontab(hour=9, minute=0),  # 9am daily
    },
    "send-sprint-health-digest": {
        "task": "src.integrations.slack.tasks.send_sprint_health_digest",
        "schedule": crontab(hour=9, minute=0, day_of_week=1),  # Monday 9am
    },
}
```

---

## Track Q: Retrospective AI — Automated Sprint Learning Engine
**Depends on MVP + Scope Cop + Dependency Radar data. Run Month 4-5.**
**Owner: `retrospective-ai-agent`**
**AI portions: YOU (agentic AI learning track)**

### Task Q1: Retrospective data model

**Files:**
- Create: `apps/api/src/models/retrospective.py`

```python
class SprintRetrospective(Base):
    __tablename__ = "sprint_retrospectives"

    id: Mapped[uuid.UUID] = ...
    sprint_id: Mapped[uuid.UUID] = ...
    team_id: Mapped[uuid.UUID] = ...

    # Auto-generated report sections
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # AI summary
    committed_points: Mapped[float] = ...
    delivered_points: Mapped[float] = ...
    spillover_rate: Mapped[float] = ...  # 0.0–1.0

    # Root cause breakdown (JSON: {"estimation": 3, "dependency": 1, "scope_creep": 2})
    slip_cause_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Detected patterns (e.g., "Auth tickets consistently overrun")
    patterns_detected: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Action items generated
    action_items: Mapped[list | None] = mapped_column(JSON, nullable=True)

    generated_at: Mapped[datetime] = ...

class RetroActionItem(Base):
    __tablename__ = "retro_action_items"

    id: Mapped[uuid.UUID] = ...
    retrospective_id: Mapped[uuid.UUID] = ...
    team_id: Mapped[uuid.UUID] = ...
    description: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = ...
    due_sprint_id: Mapped[uuid.UUID | None] = ...
    is_complete: Mapped[bool] = mapped_column(default=False)
    completed_at: Mapped[datetime | None] = ...
    jira_ticket_key: Mapped[str | None] = ...  # if action item was ticketed
```

### Task Q2: Retrospective AI service

**Files:**
- Create: `apps/api/src/services/retrospective_ai.py`

```python
# YOUR AGENTIC AI LEARNING SURFACE
async def generate_retrospective_report(
    sprint_data: dict,           # Sprint summary with all tickets + outcomes
    historical_retros: list[dict],  # Last N retrospectives for pattern detection
    anthropic_api_key: str,
) -> dict:
    """
    YOUR TASK: Generate the full automated retrospective report.

    This is the most complex AI task in the system. Recommended multi-step approach:
    Step 1: Analyse this sprint's data — what happened, why did tickets slip?
    Step 2: Compare against historical retros — are these patterns recurring?
    Step 3: Generate specific, actionable action items (not vague "improve estimation")
    Step 4: Identify the top 3 systemic issues the team should address

    Agentic enhancement: Use a multi-agent approach where one Claude call analyses
    data, another generates the report, and a third critiques and refines it.
    This produces dramatically better output than a single prompt.

    Output format: {
        "summary": str,
        "patterns_detected": [{"pattern": str, "evidence": str, "sprint_count": int}],
        "action_items": [{"description": str, "priority": "high|medium|low", "owner_hint": str}],
        "team_health_indicators": {"improving": [...], "declining": [...]}
    }
    """
    raise NotImplementedError("Retrospective AI — your implementation track")
```

### Task Q3: Auto-trigger retrospective on sprint close

**Files:**
- Modify: `apps/api/src/integrations/jira/sync.py`

```python
# When a sprint is marked as completed in Jira sync:
@celery_app.task
def on_sprint_completed(sprint_id: str):
    """Automatically trigger retrospective generation when sprint closes."""
    # 1. Calculate all velocity records for this sprint
    # 2. Tag slip causes for unfinished tickets
    # 3. Queue retrospective AI generation
    generate_retrospective.delay(sprint_id)

@celery_app.task(bind=True, max_retries=2)
def generate_retrospective(self, sprint_id: str):
    """Generate the retrospective report for a completed sprint."""
    # Calls retrospective_ai.generate_retrospective_report()
    # Saves SprintRetrospective to DB
    # Sends Slack notification to team
    pass  # retrospective-ai-agent implements
```

### Task Q4: Team Health Score

**Files:**
- Create: `apps/api/src/services/team_health.py`

```python
def calculate_team_health_score(
    recent_retros: list[dict],
    n_sprints: int = 6,
) -> dict:
    """
    Rolling metric: 0–100 score combining:
    - Sprint predictability (40%): committed vs delivered ratio
    - Velocity consistency (20%): low std dev is good
    - Improvement trend (20%): are scores getting better?
    - Action item follow-through (20%): % of retro actions completed

    Returns: {
        "score": 73,
        "trend": "improving",  # improving | stable | declining
        "breakdown": { "predictability": 80, "consistency": 70, ... }
    }
    """
    if not recent_retros:
        return {"score": None, "trend": "insufficient_data"}
    # Implementation: weight and average the four components
    ...
```

### Task Q5: Retrospective UI

**Files:**
- Create: `apps/web/src/pages/RetrospectivePage.tsx`
- Create: `apps/web/src/components/retro/SprintReportCard.tsx`
- Create: `apps/web/src/components/retro/ActionItemTracker.tsx`
- Create: `apps/web/src/components/retro/TeamHealthDashboard.tsx`
- Create: `apps/web/src/components/retro/PatternAlert.tsx`

**SprintReportCard spec:**
- Sprint name, dates, committed vs delivered stats
- Slip cause breakdown as a donut chart (Recharts PieChart)
- AI-generated summary paragraph
- "Detected patterns" section with pattern chips
- Export buttons: "Copy to Confluence" | "Copy to Notion" | "Copy Markdown"

**TeamHealthDashboard spec:**
- Large score display (0–100) with trend arrow
- 6-sprint trend line chart
- "Improving" / "Stable" / "Declining" badge
- Breakdown bar chart: predictability, consistency, improvement, action items

**ActionItemTracker spec:**
- Table: description, owner, due sprint, status
- Inline status toggle (open → complete)
- "Create Jira ticket" button per action item
- Outstanding items from previous sprints shown at top of each sprint plan

---

## Track R: Enterprise Features
**Depends on full platform working. Run Month 5.**
**Owner: `enterprise-features-agent`**

### Task R1: SSO via Clerk Organizations

> **🧑 HUMAN TASK (Agentic AI Learning):** Configure Clerk Organizations with SAML SSO support. Enable in Clerk dashboard. Test with a Google Workspace SAML flow.

**Files:**
- Create: `apps/api/src/routers/admin.py`
- Create: `apps/web/src/pages/AdminPage.tsx`

**Admin capabilities to build:**
- Manage org members and roles (GET/POST/DELETE `/api/admin/members`)
- View all team data across the org
- Configure Anthropic key for entire org (so teams don't manage it individually)
- Audit log: who accessed what data, when
- Data export: full org data as JSON/CSV

### Task R2: Audit logging

**Files:**
- Create: `apps/api/src/models/audit_log.py`

```python
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = ...
    organization_id: Mapped[uuid.UUID] = ...
    user_id: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = ...        # "viewed_velocity", "generated_plan", "exported_data"
    resource_type: Mapped[str] = ...  # "sprint", "developer", "retrospective"
    resource_id: Mapped[str | None] = ...
    metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = ...
    created_at: Mapped[datetime] = ...
```

---

## Track S: Full Platform Polish
**Run Month 5, parallel with R.**

### Task S1: Onboarding improvements
- Multi-source connection (Jira OR Linear OR GitHub — user picks)
- Team setup wizard (select board, set sprint length, add team members)
- First-sprint guided experience with empty states

### Task S2: Landing page updates
- Update `LandingPage/` with real screenshots from the app
- Add pricing page with tier comparison table
- Add "How it works" section with the 5-module loop diagram
- Real testimonials from beta users

### Task S3: Performance and reliability
- Add database indexes for all common query patterns
- Add Redis caching for velocity calculations (cache bust on new sprint data)
- Set up Railway auto-scaling
- Set up uptime monitoring (Better Uptime or similar)

---

## Full Product Launch Checklist

Before calling this "done":

- [ ] All 5 modules functional with Jira integration
- [ ] Linear integration live
- [ ] GitHub Projects integration live
- [ ] Slack notifications working (dependency nudges + sprint health digest)
- [ ] RBAC working (member can only see own velocity)
- [ ] Stripe billing for all 3 tiers
- [ ] SOC 2 Type II audit started (or at least scoped)
- [ ] GDPR data export and deletion working
- [ ] 99.9% uptime SLA achievable (Railway auto-scaling tested)
- [ ] Team Health Score showing trend data for at least 5 teams
- [ ] NPS > 40 from beta cohort
- [ ] $50k ARR target hit (25 paying teams)
