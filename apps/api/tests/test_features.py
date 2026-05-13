import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from src.config import Settings
from src.main import app


def test_local_yaml_loads():
    settings = Settings(environment="local")
    flags = settings.feature_flags
    assert flags["push_to_jira"] is True
    assert flags["retro_pattern_detection"] is True
    assert flags["skill_based_assignment"] is True
    assert flags["slack_alerts"] is True
    assert flags["dependency_radar"] is True
    assert flags["omada_simulator"] is True
    assert flags["onboarding"] is True


def test_production_yaml_loads():
    settings = Settings(environment="production")
    flags = settings.feature_flags
    assert flags["push_to_jira"] is False
    assert flags["multi_team_dashboard"] is False
    assert flags["exec_dashboard"] is False
    assert flags["retro_pattern_detection"] is False
    assert flags["slack_alerts"] is False
    assert flags["dependency_radar"] is False
    assert flags["omada_simulator"] is False
    assert flags["onboarding"] is False


def test_missing_flag_defaults_to_false():
    settings = Settings(environment="local")
    assert settings.is_feature_enabled("nonexistent_flag") is False


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
    assert "push_to_jira" in body["features"]
