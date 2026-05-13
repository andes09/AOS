from fastapi import APIRouter, Depends

from src.auth import get_current_user_id
from src.config import settings

router = APIRouter(prefix="/api/features", tags=["features"])


@router.get("")
async def get_features(_: str = Depends(get_current_user_id)):
    """Return the feature flag config for the active environment."""
    return {
        "environment": settings.environment,
        "features": settings.feature_flags,
    }
