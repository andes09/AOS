import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from src.config import Settings
from src.main import app


def test_local_yaml_loads():
    settings = Settings(environment="local")
    flags = settings.feature_flags
    assert flags["slack_alerts"] is False
    assert flags["roadmap_generation"] is True
    assert flags["planner"] is True
    assert flags["roadmap_chat"] is True
    assert flags["experimental"] == {"enabled": True, "import_artifacts": True}


def test_production_yaml_loads():
    settings = Settings(environment="production")
    flags = settings.feature_flags
    assert flags["slack_alerts"] is False
    assert flags["roadmap_generation"] is True
    assert flags["planner"] is True
    assert flags["roadmap_chat"] is False
    assert flags["experimental"] == {"enabled": False, "import_artifacts": False}


def test_is_feature_enabled_supports_dotted_path_for_grouped_flags():
    local = Settings(environment="local")
    assert local.is_feature_enabled("experimental") is True
    assert local.is_feature_enabled("experimental.enabled") is True
    assert local.is_feature_enabled("experimental.import_artifacts") is True
    assert local.is_feature_enabled("experimental.nonexistent_sub_flag") is False

    production = Settings(environment="production")
    assert production.is_feature_enabled("experimental") is False
    assert production.is_feature_enabled("experimental.enabled") is False
    assert production.is_feature_enabled("experimental.import_artifacts") is False


def test_missing_flag_defaults_to_false():
    settings = Settings(environment="local")
    assert settings.is_feature_enabled("nonexistent_flag") is False
    assert settings.is_feature_enabled("nonexistent_parent.child") is False


def test_unknown_environment_raises():
    settings = Settings(environment="banana")
    with pytest.raises(RuntimeError, match="Feature flag file not found"):
        _ = settings.feature_flags


def _mock_state(payload: dict | None):
    state = MagicMock()
    state.is_signed_in = payload is not None
    state.payload = payload
    return state


@pytest.mark.asyncio
async def test_features_endpoint_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/features")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_features_endpoint_returns_environment_and_flags():
    with patch(
        "src.auth._clerk.authenticate_request_async",
        new=AsyncMock(return_value=_mock_state({"sub": "user_abc"})),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/features", headers={"Authorization": "Bearer valid-token"}
            )

    assert response.status_code == 200
    body = response.json()
    assert "environment" in body
    assert "features" in body
    assert isinstance(body["features"], dict)
    assert "cost_tracking" in body["features"]
