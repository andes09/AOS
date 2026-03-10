# AgileOS MVP Plan

## Track D — Statistical Velocity Engine
- [ ] Per-developer velocity profiling by ticket type and domain
- [ ] Sprint capacity modelling (PTO + meetings)
- [ ] Confidence interval calculation
- [ ] Service lives in `apps/api/src/services/velocity/`

---

## Notes

> **Future: Meeting data via Calendar integration (Google Calendar / Outlook)**
> MVP uses manual input — team lead submits meeting hours per developer per sprint via API.
> Full version should replace this with a calendar sync track (Track ??) that auto-detects
> meetings and feeds them into the capacity model automatically.

> **Dependency: DB Models not yet created**
> `apps/api/src/models/` does not exist. A separate track must create SQLAlchemy models
> (`Sprint`, `Ticket`, `Developer`, `PtoEntry`) before Track D can be wired to the DB.
> Track D will be built with Pydantic input schemas as stand-ins so logic is fully decoupled
> and can be integrated once models land.
