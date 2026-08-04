import logging
import os as _os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Must run before anything else emits a log record, otherwise those early
# records hit a handler-less root logger and vanish. See logging_config.py.
from src.logging_config import setup_logging

setup_logging()

from src.config import settings  # noqa: E402
from src.auth import get_current_user_id  # noqa: E402
from src.request_logging import RequestContextMiddleware  # noqa: E402

logger = logging.getLogger(__name__)

_sentry_dsn = _os.getenv("SENTRY_DSN")
if _sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(dsn=_sentry_dsn, traces_sample_rate=0.1, environment=_os.getenv("ENVIRONMENT", "development"))
    logger.info("sentry initialised", extra={"environment": _os.getenv("ENVIRONMENT", "development")})
else:
    logger.warning("SENTRY_DSN not set — server exceptions will only be visible in stdout logs")

from src.routers import sprints as sprints_router
from src.routers import alerts as alerts_router
from src.routers import organizations as organizations_router
from src.routers.organizations import settings_router
from src.integrations.github import router as github_router
from src.routers import developers as developers_router
from src.routers.users import users_router
from src.routers.invitations import invitations_router
from src.routers.onboarding_v2 import router as onboarding_v2_router
from src.routers.artifact_import import router as artifact_import_router
from src.routers.roadmap import router as roadmap_router
from src.routers.projects import router as projects_router
from src.routers.activity import router as activity_router
from src.routers.capacity import capacity_router
from src.routers.teams import teams_router
from src.routers.features import router as features_router
from src.routers.recalibration import router as recalibration_router
from src.routers.github_webhooks import router as github_webhooks_router
from src.routers.platform_admin import router as platform_admin_router
from src.routers.mcp_oauth_consent import router as mcp_oauth_consent_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "API starting",
        extra={"environment": settings.environment, "sentry": bool(_sentry_dsn)},
    )
    # Surface a bad DATABASE_URL at boot rather than on the first user request.
    try:
        from sqlalchemy import text
        from src.database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database connectivity OK")
    except Exception:
        logger.exception("database connectivity check FAILED at startup — API will serve errors")
    yield
    logger.info("API shutting down")


app = FastAPI(
    title="Omada API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    lifespan=lifespan,
)

_allowed_origins = settings.allowed_origins
logger.info("CORS configured", extra={"allowed_origins": _allowed_origins})

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.railway\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added after CORSMiddleware so it runs *inside* it: Starlette applies
# middleware in reverse registration order, and we want the request id bound
# before any route code runs, and released after it returns.
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422s are usually a frontend/backend contract drift — log what failed.

    FastAPI's built-in handler returns the same body silently, which makes a
    broken payload shape invisible server-side.
    """
    logger.warning(
        "request validation failed for %s %s",
        request.method,
        request.url.path,
        extra={"http_path": request.url.path, "validation_errors": exc.errors()},
    )
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Log deliberate 4xx/5xx aborts, which otherwise leave no server-side trace.

    5xx raised as HTTPException is a real defect, so it gets a stack trace;
    4xx is expected control flow and stays at INFO/WARNING.
    """
    if exc.status_code >= 500:
        logger.exception(
            "HTTPException %s for %s %s", exc.status_code, request.method, request.url.path,
            extra={"http_status": exc.status_code, "http_path": request.url.path},
        )
    elif exc.status_code in (401, 403, 404):
        logger.info(
            "HTTP %s for %s %s: %s", exc.status_code, request.method, request.url.path, exc.detail,
            extra={"http_status": exc.status_code, "http_path": request.url.path},
        )
    else:
        logger.warning(
            "HTTP %s for %s %s: %s", exc.status_code, request.method, request.url.path, exc.detail,
            extra={"http_status": exc.status_code, "http_path": request.url.path},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # RequestContextMiddleware already logged this with timing + client context.
    # Only log here if it didn't (e.g. a failure raised outside its reach), so a
    # single 500 never produces two stack traces.
    if not getattr(request.state, "exception_logged", False):
        logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
    response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
    # Echo the correlation id on failures too — this is precisely the response a
    # user will screenshot, and it's the key to finding the trace in the logs.
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
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
app.include_router(github_router.router)
app.include_router(users_router, prefix="/api/users")
app.include_router(developers_router.router)
app.include_router(onboarding_v2_router)
app.include_router(artifact_import_router)
app.include_router(projects_router)
app.include_router(roadmap_router)
app.include_router(activity_router)
app.include_router(invitations_router, prefix="/api/invitations")
app.include_router(capacity_router, prefix="/api/capacity")
app.include_router(teams_router, prefix="/api/teams")
app.include_router(features_router)
app.include_router(recalibration_router, prefix="/api/recalibration")
app.include_router(github_webhooks_router)
app.include_router(platform_admin_router)
app.include_router(mcp_oauth_consent_router)


@app.get("/health")
async def health():
    # Deliberately does NOT touch the database. This is Railway's healthcheck
    # (railway.toml), so a DB round-trip here would turn pool exhaustion into a
    # failed healthcheck and a container restart — an availability risk taken on
    # for no observability gain, since DB failures are already logged at startup
    # (lifespan) and on every request that actually needs the DB.
    return {"status": "ok", "environment": settings.environment}


@app.get("/api/me")
async def get_me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}


# ─── MCP server (Omada roadmap tools for Claude Code, Claude Desktop, ...) ──────
# Mounted only when the experimental.mcp_server flag is on, and mounted LAST —
# after every other route above, including /health and /api/me — because
# FastAPI/Starlette match routes in registration order, and a Mount at "/"
# matches any path that starts with "/", i.e. everything. Placed earlier in
# the file, it would silently swallow every route defined after it (this was
# caught by inspecting app.routes directly after a first attempt placed it
# right after /health, which put it before /api/me — confirmed broken, moved
# here). This catch-all only ever handles paths nothing more specific already
# claimed (/authorize, /token, /register, /revoke, /.well-known/..., and the
# streamable-http transport path). Mounting at "/" rather than "/mcp" is also
# deliberate: FastMCP.streamable_http_app() already serves the MCP transport
# internally at streamable_http_path (default "/mcp") and registers
# .well-known/OAuth routes as root-relative — mounting the whole app at "/mcp"
# would double-nest to "/mcp/mcp" and misplace .well-known (confirmed against
# the real installed mcp==1.28.1, see docs/plans/2026-07-20-omada-mcp-server.md's
# Implementation Notes).
if settings.is_feature_enabled("experimental.mcp_server"):
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
    from mcp.server.fastmcp import FastMCP

    from src.mcp_server.oauth_provider import OmadaOAuthProvider
    from src.mcp_server.tools import register_tools

    _mcp = FastMCP(
        "omada",
        auth_server_provider=OmadaOAuthProvider(),
        auth=AuthSettings(
            issuer_url=settings.api_url,
            resource_server_url=f"{settings.api_url}/mcp",
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["roadmap"],
                default_scopes=["roadmap"],
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
    )
    register_tools(_mcp)
    app.mount("/", _mcp.streamable_http_app())
