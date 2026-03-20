# AgileOS MVP Plan

## Track D — Statistical Velocity Engine
- [ ] Per-developer velocity profiling by ticket type and domain
- [ ] Sprint capacity modelling (PTO + meetings)
- [ ] Confidence interval calculation
- [ ] Service lives in `apps/api/src/services/velocity/`

---

## Deferred

- [ ] **Redis + Celery setup** — Jira sync tasks are enqueued via Celery but Redis isn't running locally.
  Start Redis (`redis-server`) and a Celery worker (`celery -A src.worker worker`) to enable background sync.
  The `sync_jira_team` task after board selection silently skips if broker is unavailable (by design for now).
  Also note: sync uses `team.jira_board_id` with the agile board API, which needs to be updated to use
  project-based sprint fetching since `aosTest` is a team-managed project (agile API not supported).

---

## Notes

> **Future: Meeting data via Calendar integration (Google Calendar / Outlook)**
> MVP uses manual input — team lead submits meeting hours per developer per sprint via API.
> Full version should replace this with a calendar sync track (Track ??) that auto-detects
> meetings and feeds them into the capacity model automatically.

> **Future: Custom domain granularity for velocity profiling**
> The velocity engine currently uses a fixed `Domain` enum (`frontend`, `backend`, `infra`).
> Consider allowing teams to define custom domains (e.g. `mobile`, `data`, `devops`) so that
> velocity profiles and Sprint Brain citations reflect the team's actual work taxonomy.
> Would require extending `Domain` in Track D's schemas and a migration path for existing data.

> **Dependency: DB Models not yet created**
> `apps/api/src/models/` does not exist. A separate track must create SQLAlchemy models
> (`Sprint`, `Ticket`, `Developer`, `PtoEntry`) before Track D can be wired to the DB.
> Track D will be built with Pydantic input schemas as stand-ins so logic is fully decoupled
> and can be integrated once models land.

> **Future: Clerk Webhook Handler**
> `clerk_webhook_secret` is currently optional and unused. If user data needs to be synced
> to the local DB on signup/update (e.g. creating a `User` record on `user.created` event),
> a webhook handler must be built at `POST /api/webhooks/clerk` using svix signature
> verification. Required events: `user.created`, `user.updated`, `user.deleted`.
