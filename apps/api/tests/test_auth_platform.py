"""Direct unit tests for src/auth_platform.py's require_platform_admin
dependency and Settings.platform_admin_ids parsing — HTTP-level 403/200/404
behavior through the actual router is covered in test_platform_admin.py."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.auth_platform import require_platform_admin
from src.config import Settings, settings


def test_platform_admin_ids_empty_by_default():
    s = Settings(environment="test", platform_admin_user_ids="")
    assert s.platform_admin_ids == set()


def test_platform_admin_ids_parses_comma_separated_and_strips_whitespace():
    s = Settings(environment="test", platform_admin_user_ids="user_a, user_b,user_c ")
    assert s.platform_admin_ids == {"user_a", "user_b", "user_c"}


async def test_require_platform_admin_raises_403_when_not_allowlisted():
    with patch.object(settings, "platform_admin_user_ids", "someone_else"):
        with pytest.raises(HTTPException) as exc:
            await require_platform_admin(user_id="user_x")
    assert exc.value.status_code == 403


async def test_require_platform_admin_raises_403_when_allowlist_empty():
    with patch.object(settings, "platform_admin_user_ids", ""):
        with pytest.raises(HTTPException) as exc:
            await require_platform_admin(user_id="user_x")
    assert exc.value.status_code == 403


async def test_require_platform_admin_passes_when_allowlisted():
    with patch.object(settings, "platform_admin_user_ids", "user_x,user_y"):
        result = await require_platform_admin(user_id="user_x")
    assert result == "user_x"
