import logging
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.config import settings
from src.auth import get_current_user_id

logger = logging.getLogger(__name__)
from src.routers import sprint_brain as sprint_brain_router
from src.routers import velocity as velocity_router
from src.routers import sprints as sprints_router
from src.routers import alerts as alerts_router
from src.routers import organizations as organizations_router
from src.routers.organizations import settings_router
from src.routers.exec import exec_router
from src.integrations.jira import router as jira_router
from src.routers import developers as developers_router
from src.routers.users import users_router
from src.routers.scope_cop import scope_cop_router
from src.routers.dependency_radar import dependency_radar_router
from src.routers.retro import retro_router
from src.routers.onboarding import onboarding_router, invitations_router
from src.routers.capacity import capacity_router
from src.routers.teams import teams_router
from src.routers.slack import slack_router

app = FastAPI(
    title="Omada API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(sprint_brain_router.router)
app.include_router(velocity_router.router)
app.include_router(velocity_router.dashboard_router)
app.include_router(sprints_router.router)
app.include_router(alerts_router.router)
app.include_router(organizations_router.router)
app.include_router(settings_router)
app.include_router(jira_router.router)
app.include_router(users_router, prefix="/api/users")
app.include_router(exec_router, prefix="/api/exec")
app.include_router(developers_router.router)
app.include_router(scope_cop_router, prefix="/api/scope-cop")
app.include_router(dependency_radar_router, prefix="/api/dependency-radar")
app.include_router(retro_router, prefix="/api/retro")
app.include_router(onboarding_router, prefix="/api/onboarding")
app.include_router(invitations_router, prefix="/api/invitations")
app.include_router(capacity_router, prefix="/api/capacity")
app.include_router(teams_router, prefix="/api/teams")
app.include_router(slack_router, prefix="/api/teams")


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/api/me")
async def get_me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}
