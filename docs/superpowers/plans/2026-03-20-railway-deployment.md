# Railway Deployment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the AOS API (FastAPI), Celery worker, and Celery beat to Railway, with the React frontend deployed to Vercel.

**Architecture:** Single Dockerfile for the API image, used by three Railway services (API, worker, beat) with different start commands. Frontend is a static build deployed to Vercel (simpler, faster CDN, free). Alembic migrations run as a Railway deploy hook before the API starts.

**Tech Stack:** Railway (API/worker/beat), Vercel (frontend), PostgreSQL on Railway, Redis on Railway, Docker/uvicorn, Celery.

---

## Chunk 1: API Dockerfile + production config

### Task 1: Create the API Dockerfile

**Files:**
- Create: `apps/api/Dockerfile`

- [ ] **Step 1: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev deps)
RUN uv sync --frozen --no-dev

# Copy source
COPY . .

# Default command (overridden per Railway service)
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Verify it builds locally**

```bash
cd apps/api
docker build -t aos-api .
```

Expected: `Successfully built ...`

- [ ] **Step 3: Commit**

```bash
git add apps/api/Dockerfile
git commit -m "feat: add API Dockerfile for Railway deployment"
```

---

### Task 2: Create railway.toml

**Files:**
- Create: `apps/api/railway.toml`

- [ ] **Step 1: Create railway.toml**

```toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "uv run alembic upgrade head && uv run uvicorn src.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
```

Note: `alembic upgrade head` runs migrations before every deploy — safe because Alembic is idempotent.

- [ ] **Step 2: Commit**

```bash
git add apps/api/railway.toml
git commit -m "feat: add Railway config for API service"
```

---

### Task 3: Harden production config

**Files:**
- Modify: `apps/api/src/config.py`
- Modify: `apps/api/src/main.py`

- [ ] **Step 1: Update CORS to support production frontend URL**

In `apps/api/src/main.py`, replace the single allowed origin with a list:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "https://your-app.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Actually, cleaner — make `frontend_url` support comma-separated origins in config:

In `apps/api/src/config.py`, add:
```python
frontend_url: str = "http://localhost:5174"

@property
def allowed_origins(self) -> list[str]:
    return [u.strip() for u in self.frontend_url.split(",")]
```

In `apps/api/src/main.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/src/config.py apps/api/src/main.py
git commit -m "feat: support comma-separated CORS origins for production"
```

---

## Chunk 2: Railway service setup

### Task 4: Set up Railway project services

This is done in the Railway dashboard — no code changes.

- [ ] **Step 1: Create Railway project**
  - Go to railway.app → New Project → Empty Project
  - Name it `aos`

- [ ] **Step 2: Add PostgreSQL service**
  - Click `+ New` → Database → PostgreSQL
  - Note the `DATABASE_URL` from the Variables tab (public URL for migrations, internal for runtime)

- [ ] **Step 3: Add Redis service**
  - Click `+ New` → Database → Redis
  - Note the `REDIS_URL` from the Variables tab

- [ ] **Step 4: Add API service**
  - Click `+ New` → GitHub Repo → select your repo
  - Set Root Directory: `apps/api`
  - Railway will detect the Dockerfile automatically
  - Do NOT deploy yet — set env vars first (Task 5)

- [ ] **Step 5: Add Celery Worker service**
  - Click `+ New` → GitHub Repo → same repo
  - Set Root Directory: `apps/api`
  - Override Start Command: `uv run celery -A src.worker worker --loglevel=info --concurrency=2`
  - Do NOT deploy yet

- [ ] **Step 6: Add Celery Beat service**
  - Click `+ New` → GitHub Repo → same repo
  - Set Root Directory: `apps/api`
  - Override Start Command: `uv run celery -A src.worker beat --loglevel=info`
  - Do NOT deploy yet

---

### Task 5: Set environment variables in Railway

Set these on the **API service**, **Worker service**, and **Beat service** (all three need them). Use Railway's "shared variables" or set per service.

- [ ] **Step 1: Set variables on API service**

In Railway → API service → Variables, add:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Railway internal Postgres URL (`postgresql+asyncpg://...railway.internal...`) |
| `DATABASE_URL_SYNC` | Same but `postgresql+psycopg2://...railway.internal...` |
| `REDIS_URL` | Railway internal Redis URL (`redis://...railway.internal...`) |
| `CLERK_SECRET_KEY` | From Clerk dashboard |
| `CLERK_PUBLISHABLE_KEY` | From Clerk dashboard |
| `CLERK_WEBHOOK_SECRET` | From Clerk dashboard |
| `ENCRYPTION_KEY` | Your 32-byte hex key (same as local .env) |
| `JIRA_CLIENT_ID` | From Atlassian developer console |
| `JIRA_CLIENT_SECRET` | From Atlassian developer console |
| `JIRA_REDIRECT_URI` | `https://your-api.railway.app/api/integrations/jira/callback` |
| `FRONTEND_URL` | `https://your-app.vercel.app` (set after Vercel deploy) |
| `ENVIRONMENT` | `production` |

- [ ] **Step 2: Copy same variables to Worker and Beat services**

Worker and Beat need: `DATABASE_URL`, `DATABASE_URL_SYNC`, `REDIS_URL`, `ENCRYPTION_KEY`, `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`, `CLERK_SECRET_KEY`

- [ ] **Step 3: Update asyncpg URL format**

Railway's Postgres URL uses `postgresql://` — asyncpg needs `postgresql+asyncpg://`. In Railway variables set:
- `DATABASE_URL` = `postgresql+asyncpg://postgres:PASSWORD@postgres.railway.internal:5432/railway`
- `DATABASE_URL_SYNC` = `postgresql+psycopg2://postgres:PASSWORD@postgres.railway.internal:5432/railway`

- [ ] **Step 4: Deploy all services**
  - Trigger deploy on API, Worker, Beat services
  - Watch logs — API should run migrations then start uvicorn

---

## Chunk 3: Frontend deployment to Vercel

### Task 6: Deploy frontend to Vercel

**Files:**
- Create: `apps/web/.env.production` (gitignored — set in Vercel dashboard instead)

- [ ] **Step 1: Push current code to GitHub**

```bash
git push origin feat/onboarding
```

Or merge to main first if ready.

- [ ] **Step 2: Deploy to Vercel**
  - Go to vercel.com → New Project → import your GitHub repo
  - Set Root Directory: `apps/web`
  - Framework: Vite (auto-detected)
  - Add environment variables in Vercel dashboard:

| Variable | Value |
|---|---|
| `VITE_API_URL` | `https://your-api.railway.app` |
| `VITE_CLERK_PUBLISHABLE_KEY` | From Clerk dashboard |

- [ ] **Step 3: After Vercel deploy, update FRONTEND_URL in Railway**
  - Copy the Vercel deployment URL (e.g. `https://aos-abc123.vercel.app`)
  - Update `FRONTEND_URL` in Railway API service variables
  - Trigger redeploy of API service

- [ ] **Step 4: Update Clerk allowed origins**
  - In Clerk dashboard → your app → Settings → Domains
  - Add your Vercel URL as an allowed origin

- [ ] **Step 5: Update Jira OAuth redirect URI**
  - In Atlassian developer console → your OAuth app → Authorization
  - Add `https://your-api.railway.app/api/integrations/jira/callback` as a callback URL

---

## Chunk 4: Verify end-to-end

### Task 7: Smoke test production

- [ ] **Step 1: Check API health**

```bash
curl https://your-api.railway.app/health
```

Expected: `{"status":"ok","environment":"production"}`

- [ ] **Step 2: Check migrations ran**

In Railway → API service → Logs, look for:
```
INFO  [alembic.runtime.migration] Running upgrade ...
```

- [ ] **Step 3: Check Celery worker connected**

In Railway → Worker service → Logs, look for:
```
celery@... ready.
```

- [ ] **Step 4: Open frontend and complete onboarding**
  - Sign in via Clerk
  - Connect Jira
  - Select board/project
  - Save Anthropic key

- [ ] **Step 5: Trigger manual Jira sync to verify worker works**

```bash
curl -X POST https://your-api.railway.app/api/integrations/jira/sync \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"team_id": "YOUR_TEAM_ID"}'
```

Check Worker logs for sync activity.

- [ ] **Step 6: Check Railway logs for any errors and fix**

---

## Environment Variables Reference

For local `.env` (dev):
```env
DATABASE_URL=postgresql+asyncpg://postgres:PASSWORD@monorail.proxy.rlwy.net:PORT/railway
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:PASSWORD@monorail.proxy.rlwy.net:PORT/railway
REDIS_URL=redis://default:PASSWORD@monorail.proxy.rlwy.net:PORT
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_WEBHOOK_SECRET=whsec_...
ENCRYPTION_KEY=<your-32-byte-hex>
JIRA_CLIENT_ID=...
JIRA_CLIENT_SECRET=...
JIRA_REDIRECT_URI=http://localhost:8000/api/integrations/jira/callback
FRONTEND_URL=http://localhost:5174
ENVIRONMENT=development
```
