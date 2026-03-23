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
from src.integrations.jira import router as jira_router

app = FastAPI(
    title="AgileOS API",
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


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/api/me")
async def get_me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}
