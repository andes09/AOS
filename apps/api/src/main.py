from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from src.config import settings
from src.auth import get_current_user_id
from src.routers import sprint_brain as sprint_brain_router
from src.routers import velocity as velocity_router

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


app.include_router(sprint_brain_router.router)
app.include_router(velocity_router.router)


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/api/me")
async def get_me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}
