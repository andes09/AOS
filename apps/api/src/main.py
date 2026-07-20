import logging
import os as _os
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.config import settings
from src.auth import get_current_user_id

logger = logging.getLogger(__name__)

_sentry_dsn = _os.getenv("SENTRY_DSN")
if _sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(dsn=_sentry_dsn, traces_sample_rate=0.1, environment=_os.getenv("ENVIRONMENT", "development"))

from src.routers import sprints as sprints_router
from src.routers import alerts as alerts_router
from src.routers import organizations as organizations_router
from src.routers.organizations import settings_router
from src.integrations.jira import router as jira_router
from src.integrations.github import router as github_router
from src.routers import developers as developers_router
from src.routers.users import users_router
from src.routers.scope_cop import scope_cop_router
from src.routers.scope_cop_revisions import scope_cop_revisions_router
from src.routers.invitations import invitations_router
from src.routers.onboarding_v2 import router as onboarding_v2_router
from src.routers.roadmap import router as roadmap_router
from src.routers.capacity import capacity_router
from src.routers.teams import teams_router
from src.routers.slack import slack_router
from src.routers.features import router as features_router
from src.routers.identifiers import router as identifiers_router
from src.routers.recalibration import router as recalibration_router

app = FastAPI(
    title="Omada API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
)

_allowed_origins = settings.allowed_origins
print(f"[CORS] allowed_origins={_allowed_origins}", flush=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.railway\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
    response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
    # ServerErrorMiddleware sits OUTSIDE CORSMiddleware, so 500s skip the CORS
    # layer and reach the browser without CORS headers — surfacing as a
    # misleading "blocked by CORS policy" error. Re-add them here so the real
    # 500 is visible to the frontend.
    import re as _re
    origin = request.headers.get("origin")
    _railway_re = r"https://.*\.railway\.app"
    if origin and (origin in settings.allowed_origins or _re.fullmatch(_railway_re, origin)):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


app.include_router(sprints_router.router)
app.include_router(alerts_router.router)
app.include_router(organizations_router.router)
app.include_router(settings_router)
app.include_router(jira_router.router)
app.include_router(github_router.router)
app.include_router(users_router, prefix="/api/users")
app.include_router(developers_router.router)
app.include_router(scope_cop_router, prefix="/api/scope-cop")
app.include_router(scope_cop_revisions_router, prefix="/api/scope-cop")
app.include_router(onboarding_v2_router)
app.include_router(roadmap_router)
app.include_router(invitations_router, prefix="/api/invitations")
app.include_router(capacity_router, prefix="/api/capacity")
app.include_router(teams_router, prefix="/api/teams")
app.include_router(slack_router, prefix="/api/teams")
app.include_router(features_router)
app.include_router(identifiers_router, prefix="/api/identifiers")
app.include_router(recalibration_router, prefix="/api/recalibration")


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/api/me")
async def get_me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}
