import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from src.config import Settings
from src.main import app


#: Flags every environment file must define, so a missing key is caught rather
#: than silently defaulting to off at a call site.
_REQUIRED_TOP_LEVEL = {"clerk_auth", "cost_tracking", "roadmap_generation", "plan_review", "repo_create"}
_ENVIRONMENTS = ("local", "production", "test")


# These used to assert exact equality against the whole `experimental` dict,
# which meant every new experimental flag broke both tests in a way that said
# nothing about correctness — it drifted twice before anyone noticed. What
# actually matters is asserted directly instead: the shipped flags have their
# intended values, every environment defines the same key set, and nothing
# experimental is on in production.
def test_local_yaml_loads():
    flags = Settings(environment="local").feature_flags
    assert _REQUIRED_TOP_LEVEL <= flags.keys()
    assert flags["roadmap_generation"] is True
    assert flags["planner"] == {
        "enabled": True, "week_view": False, "daily_calendar_view": False, "board_view": False,
    }
    assert flags["roadmap_chat"] is True
    assert flags["plan_review"] is True
    assert flags["repo_create"] is True


def test_production_yaml_loads():
    flags = Settings(environment="production").feature_flags
    assert _REQUIRED_TOP_LEVEL <= flags.keys()
    assert flags["roadmap_generation"] is True
    assert flags["planner"] == {
        "enabled": True, "week_view": True, "daily_calendar_view": True, "board_view": True,
    }
    assert flags["roadmap_chat"] is False
    assert flags["plan_review"] is True
    assert flags["repo_create"] is True


def test_nothing_experimental_is_enabled_in_production():
    """The invariant the old exact-dict assertion was really protecting.

    Unlike that version, this keeps holding as flags are added — a new
    experimental flag accidentally shipped as `true` fails here by name.
    """
    experimental = Settings(environment="production").feature_flags["experimental"]
    enabled = [name for name, value in experimental.items() if value]
    assert enabled == [], f"experimental flags enabled in production: {enabled}"


def test_every_environment_declares_the_same_experimental_flags():
    """Catches the real drift bug: adding a flag to local.yaml but forgetting
    production.yaml or test.yaml, which reads as "off" with no error anywhere
    (recorded in tasks/todo.md as a past incident)."""
    key_sets = {
        env: set(Settings(environment=env).feature_flags["experimental"].keys())
        for env in _ENVIRONMENTS
    }
    reference = key_sets["local"]
    for env, keys in key_sets.items():
        assert keys == reference, f"{env}.yaml experimental flags differ: {keys ^ reference}"


def test_is_feature_enabled_supports_dotted_path_for_grouped_flags():
    local = Settings(environment="local")
    assert local.is_feature_enabled("experimental") is False
    assert local.is_feature_enabled("experimental.enabled") is False
    assert local.is_feature_enabled("experimental.import_artifacts") is False
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
