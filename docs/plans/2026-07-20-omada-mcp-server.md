# Omada MCP Server

## Context

Omada is pivoting toward being the AI project manager for a team's roadmap (`Organization` → `Team` → `Project` → `Milestone` → `Task`, built via `apps/api/src/routers/roadmap.py`). Right now the only way to read or update that roadmap is the web app. The ask here is to let users **connect their own coding agents (Claude Code, Claude Desktop, Cursor, etc.) directly to their Omada roadmap** via MCP — so an agent can check what it should work on next, and report back when it's done, without a human relaying that through the UI. This is also the natural counterpart to the in-flight (uncommitted) GitHub auto-complete plan (`docs/plans/2026-07-20-github-task-autocomplete.md`): that plan closes the loop from *commits → task status*; this one closes the loop from *agent → task status* directly.

No MCP code, and no API-key/M2M auth mechanism of any kind, exists in the repo today — Omada's only auth path is Clerk JWT verification for browser sessions (`apps/api/src/auth.py`). This plan builds both from scratch, scoped to a deliberately small v1 tool surface (read/query + a couple of agent-workflow actions + one gated AI-replan action) rather than a general CRUD API.

## Decisions

- **Mounted inside `apps/api`**, not a separate service — the MCP tools call the same DB/service layer directly, no network hop, no duplicated business logic.
- **Auth: OAuth 2.1, with Clerk doing the actual login.** MCP clients do the authorization-code+PKCE dance against Omada itself (Clerk can't be the AS directly — it doesn't support the dynamic client registration MCP clients rely on). Omada acts as a thin OAuth Authorization Server: the `/authorize` step redirects into a normal `apps/web` page gated by Clerk's existing `<SignedIn>`, which — once the user is confirmed logged in via Clerk — calls a new backend endpoint to mint an Omada-owned authorization code. Token exchange then issues Omada's own opaque access/refresh tokens (hashed at rest), never Clerk JWTs, so tool calls don't need a Clerk JWKS round-trip.
- **Transport: remote Streamable HTTP** (not stdio) — this is a hosted multi-tenant endpoint any user's agent connects to remotely.
- **v1 tool scope**: read/query tools, two agent-workflow tools (`get_next_task`, `complete_task`), and one gated AI-replan tool (`regenerate_milestone`). No generic `create_task`/`update_task`/`reschedule_task` — kept out to keep the initial surface small and hard to misuse.

## Grounding in the existing code

- `apps/api/src/routers/roadmap.py` (786 lines) has all roadmap logic **inline** in route handlers plus private helpers (`_get_org`, `_owned_task`, `_owned_developer`, `_owned_milestone`, `_task_json`, `_validate_status`, etc.) — no service-layer module exists yet. This must be extracted so MCP tools and REST handlers share one implementation instead of duplicating it.
- `Task` (`apps/api/src/models/task.py`) has no `completed_at` or note field — must be added; this plan does not depend on the separate uncommitted auto-complete plan landing first (that plan wants the same column — leave a note in both so whichever lands second treats it as additive/no-op).
- `Task` has no dependency graph (only the legacy `Ticket`/Jira-era `Dependency` model exists) — `get_next_task` cannot mean "next *unblocked* task" in any real sense yet; it means "next task by schedule order," and should be named/described that way rather than implying blocking-awareness that doesn't exist.
- Auth today (`apps/api/src/auth.py`) verifies Clerk JWTs directly; `auth_roles.py`'s `get_current_app_role`/`require_role` depend on that Clerk JWT via FastAPI `Depends`. MCP tool calls carry an Omada-minted opaque token instead, so the `regenerate_milestone` role gate needs its own non-Clerk check reusing the same `ROLE_HIERARCHY` comparison, not a second copy of it.
- Precedent to reuse directly: `apps/api/src/models/oauth_state.py` / `apps/api/alembic/versions/0022_oauth_state_table.py` for short-TTL DB-backed OAuth rows (raw-SQL migration style, no `op.create_table`); `apps/web/src/pages/InviteAcceptPage.tsx` + its `/invite` route in `apps/web/src/App.tsx` for the exact "Clerk-gated page that POSTs to a backend endpoint via `useApi()`'s auto-attached JWT" pattern the new consent page needs — no new frontend auth plumbing required. Latest Alembic revision is `0031`; new ones start at `0032`.
- The official MCP Python SDK (`mcp` on PyPI, currently 1.28.1) is not yet a dependency but has OAuth 2.1 AS scaffolding (`mcp.server.auth`, `OAuthAuthorizationServerProvider` protocol) plus a `FastMCP` server mountable as an ASGI sub-app with Streamable HTTP transport — this is what the plan builds against, rather than hand-rolling OAuth.

## Implementation

### 1. Service-layer extraction (prerequisite, land first)

New `apps/api/src/services/roadmap_service.py`. Move the JSON builders (`task_json`, `member_json`, `milestone_json`, `project_json`, `initials`), lookups (`get_org`, `load_project`, `get_owned_task`, `get_owned_developer`, `get_owned_tasks`, `get_owned_milestone`, `get_session_and_brief`), and validators (`_validate_status`, `_validate_title`, `_validate_duration`) out of `roadmap.py`, dropping the leading underscore where they become shared public functions. Add net-new functions needed by MCP but with no REST equivalent today:
- `list_tasks(org, db, *, status=None, assignee_id=None, milestone_id=None, scheduled_after=None, scheduled_before=None)`
- `get_members(org, db)` / `get_status(org, db)` — extracted verbatim from the existing `GET /members` / `GET /status` handler bodies
- `claim_next_task(org, developer, db)` — `SELECT` scoped to the org via the same 3-way `Task→Milestone→Project→Team` join, `WHERE status='todo' AND assignee_id IS NULL`, ordered by `scheduled_date` (nulls last), then milestone/task `sort_order`, `LIMIT 1`; assigns it to `developer.id`. Returns `None` if nothing's claimable.
- `complete_task(task, note, db)` — sets `status="done"`, `completed_at=utcnow()`, `completion_note=note` (only overwritten when `note is not None`, so re-calling without a note doesn't clobber a prior one).

`roadmap.py`'s route handlers become thin adapters over this module — resolve org/user via existing Clerk deps, call the service function, shape the HTTP response. Run the existing `apps/api/tests/test_roadmap.py` suite unmodified afterward (repoint any `patch(...)` targets that reference the old router-module private names) to confirm this is a pure move with no behavior change.

### 2. `Task` model addition

`apps/api/src/models/task.py`: add `completed_at: Mapped[datetime | None]` and `completion_note: Mapped[str | None]`. Migration `apps/api/alembic/versions/0032_task_completion_fields.py`.

### 3. OAuth tables

Migration `apps/api/alembic/versions/0033_mcp_oauth_tables.py`, raw-SQL style matching `0022`. Three new models in `apps/api/src/models/`:

- **`oauth_client.py` → `oauth_clients`** — `client_id` (PK), `client_secret_hash` (nullable — public PKCE clients have none), `client_name`, `redirect_uris` (JSON list), `grant_types`, `token_endpoint_auth_method` (default `"none"`), `scope`, `created_at`. Populated via Dynamic Client Registration (RFC 7591) since MCP clients self-register at connect time.
- **`oauth_authorization_code.py` → `oauth_authorization_codes`** — `code` (PK), `client_id` (FK), `redirect_uri`, `code_challenge` + `code_challenge_method` (PKCE), `scope`, `clerk_user_id`, `clerk_org_id`, `developer_id` (FK → `developers.id`, **not nullable** — see risk #1 below), `expires_at` (60–120s TTL), `used_at` (one-time-use enforcement), `created_at`. Index on `expires_at` for cleanup, mirroring `0022`.
- **`oauth_token.py` → `oauth_tokens`** — `id`, `token_hash` (SHA-256 hex of the opaque bearer string — **hash, never reversibly encrypt**; this is the opposite direction from `apps/api/src/services/encryption.py`'s Jira-token use, which stores tokens Omada must present back to a third party), `token_type` (`access`/`refresh`), `client_id` (FK), `clerk_user_id`, `clerk_org_id`, `developer_id` (FK — re-resolved fresh on every tool call, never trusted stale off the token, so a role change or removal takes effect immediately), `scope`, `parent_token_id` (self-FK linking a refresh token to its access token, for cascade revocation), `expires_at`, `revoked_at`, `created_at`.

### 4. OAuth Authorization Server + MCP tools

New package `apps/api/src/mcp_server/` (named to avoid shadowing the `mcp` PyPI package):

- **`oauth_provider.py`** — `OmadaOAuthProvider` implementing `mcp.server.auth.provider.OAuthAuthorizationServerProvider`: `get_client`/`register_client` (read/write `oauth_clients`), `authorize` (redirects the browser to `{frontend_url}/mcp/authorize?...` — no login UI of its own), `load_authorization_code`/`exchange_authorization_code` (verify PKCE, mark `used_at`, mint access+refresh tokens), `load_refresh_token`/`exchange_refresh_token` (rotate on use), `load_access_token` (hash lookup, check not expired/revoked), `revoke_token`.
- **`apps/api/src/routers/mcp_oauth_consent.py`** — `POST /api/mcp/oauth/consent`, depends on the *existing* `get_current_user_id`/`get_current_org_id` Clerk deps (this is the actual point where Clerk's login satisfies the OAuth flow). Resolves the caller's `Developer`, validates `client_id`/`redirect_uri` against `oauth_clients`, inserts the authorization code row, returns a redirect URL for the frontend to follow.
- **`tools.py`** — the 8 `@mcp.tool()` functions (below). Each resolves `(org, developer)` from the verified token's `clerk_org_id`/`developer_id` — never from a model-supplied parameter — so the multi-tenant boundary holds regardless of what the calling LLM is prompted to pass.
- **Mounting in `main.py`**: `FastMCP("omada", auth=OmadaOAuthProvider(...))`, mounted at `/mcp` via `.streamable_http_app()`, plus `include_router(mcp_oauth_consent_router)`, both gated behind a new `mcp_server` feature flag (`apps/api/config/features/{local,production}.yaml`, default `false`, mirroring the `clerk_auth` pattern in `apps/api/src/auth.py`).
- **`pyproject.toml`**: add `mcp>=1.28.1`.
- **`apps/api/src/database.py`**: extract `get_db`'s body into an `async with db_session():` context manager, since FastMCP tool functions aren't FastAPI handlers and can't use `Depends(get_db)`.

### 5. `apps/web` consent page

`apps/web/src/pages/McpAuthorizePage.tsx`, new `/mcp/authorize` route in `apps/web/src/App.tsx`, gated `<SignedIn>` — modeled directly on `InviteAcceptPage.tsx`. Reads `client_id, redirect_uri, code_challenge, code_challenge_method, scope, state, client_name` from the query string, shows "`{client_name}` wants access to your Omada roadmap," and on Approve calls `POST /api/mcp/oauth/consent` via the existing `useApi()` hook (which already auto-attaches the Clerk JWT) then redirects to the returned URL. On Deny, redirects straight to `redirect_uri?error=access_denied&state=...`.

### 6. The 8 v1 tools

| Tool | Behavior |
|---|---|
| `get_roadmap` | Full project + milestones + tasks for the caller's org |
| `get_task` | Single task by ID, scoped to the caller's org |
| `list_tasks` | Filter by status / assignee / milestone / scheduled date range |
| `list_team_members` | Roster + workload |
| `get_roadmap_status` | Onboarding/planning readiness check |
| `get_next_task` | Claims the next todo task by schedule order, self-assigns it to the caller's own `Developer` (the agent acts on behalf of the human who connected it — no separate bot identity); returns a clean "nothing to do" result when empty |
| `complete_task` | Marks a task done, sets `completed_at` + optional free-text `completion_note` |
| `regenerate_milestone` | Triggers AI replanning of a milestone. Gated to `lead`+ role (fresh DB lookup, not cached on the token). Requires an explicit `confirmed: bool` input — if false/omitted, returns "confirmation required" without touching data, since this costs LLM spend and destructively replans existing tasks, and MCP has no universal human-confirmation primitive to rely on instead |

### Files

**New:** `apps/api/alembic/versions/0032_task_completion_fields.py`, `0033_mcp_oauth_tables.py`; `apps/api/src/models/{oauth_client,oauth_authorization_code,oauth_token}.py`; `apps/api/src/services/roadmap_service.py`; `apps/api/src/mcp_server/{__init__.py,oauth_provider.py,tools.py}`; `apps/api/src/routers/mcp_oauth_consent.py`; `apps/web/src/pages/McpAuthorizePage.tsx`.

**Modified:** `apps/api/src/models/task.py`; `apps/api/src/routers/roadmap.py` (stripped to thin adapters); `apps/api/src/auth_roles.py` (extract a plain `role_at_least(role, minimum)` predicate used by both `require_role` and the MCP gate); `apps/api/src/database.py`; `apps/api/src/main.py`; `apps/api/config/features/{local,production}.yaml`; `apps/api/pyproject.toml`; `apps/web/src/App.tsx`.

## Verification

1. **Migrations**: `alembic upgrade head` → `alembic downgrade -2` → `upgrade head` round-trips cleanly.
2. **Service-layer refactor**: existing `apps/api/tests/test_roadmap.py` suite passes unmodified (behavior-preserving move).
3. **OAuth flow**, new `apps/api/tests/test_mcp_oauth.py` using the existing `_patch_clerk` + `tmp_db` fixtures: register a client, POST to `/api/mcp/oauth/consent` with a faked Clerk session, exchange the resulting code (+ PKCE verifier) at the SDK's `/token` endpoint, call one tool with the returned bearer token, assert it's scoped to the seeded org and rejected for a different org's data.
4. **Real client smoke test** once deployed to dev: `claude mcp add --transport http omada https://<dev-host>/mcp`, complete the browser consent step against a real Clerk session, confirm a tool call succeeds end-to-end.
5. **Per-tool tests**: seed the same fixtures `test_roadmap.py` already builds and call each of the 8 tools directly, asserting org-scoping (a task in a different org is invisible), `get_next_task`'s ordering/self-assignment, `complete_task`'s idempotency, and `regenerate_milestone`'s role gate + confirmation gate.

## Open risks (flag before/while building, not blocking the plan)

1. **No `Developer` row for the connecting Clerk user** — `get_current_app_role` silently defaults such users to `"developer"` for REST, but MCP can't do that silently (needs a real `developer_id` to assign tasks to and to mint tokens against). Plan: reject at `/api/mcp/oauth/consent` with a clear 409 rather than mirroring the REST-side default — confirm this is acceptable before building.
2. **`AccessToken` extension mechanism is unverified against the installed SDK** — the plan assumes subclassing `mcp`'s `AccessToken` with `clerk_org_id`/`clerk_user_id`/`developer_id` round-trips through the SDK's bearer-auth middleware into tool-handler context. Needs a short spike against real `mcp==1.28.1` before committing; a `contextvars` fallback exists if not.
3. **`.well-known` route placement** (root vs. under `/mcp`) for AS metadata (RFC 8414) vs protected-resource metadata (RFC 9728) needs confirming against the SDK's actual mounting helper — wrong placement breaks client auto-discovery even though manual token exchange still works.
4. **Token lifetimes** (suggested: access 1h, refresh 90d) are placeholders worth a deliberate call given these are long-lived roadmap-scoped credentials.
5. **Unbounded DCR registration** (`oauth_clients` growth) isn't rate-limited in v1 — acceptable to defer, not a launch blocker.
6. **Interaction with the uncommitted GitHub auto-complete plan**, which also wants `Task.completed_at` — whichever of the two plans lands second should treat that column as additive/no-op rather than re-adding it.
