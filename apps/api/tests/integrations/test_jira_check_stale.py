"""Wave 1 / SB-6 — JiraClient.check_stale optimistic-concurrency helper.

Mocks ``httpx.AsyncClient`` the same way as ``test_jira_update_issue.py``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integrations.jira.client import JiraClient


def _make_get_mock(updated: str | None):
    """httpx.AsyncClient mock whose .get() returns an issue with fields.updated."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={"key": "PROJ-1", "fields": {"updated": updated}}
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_check_stale_jira_newer_returns_true():
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_client = _make_get_mock("2026-05-28T12:00:00.000+0000")
    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        stale = await client.check_stale("PROJ-1", "2026-05-27T10:00:00.000+0000")
    assert stale is True


@pytest.mark.asyncio
async def test_check_stale_jira_older_returns_false():
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_client = _make_get_mock("2026-05-26T08:00:00.000+0000")
    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        stale = await client.check_stale("PROJ-1", "2026-05-27T10:00:00.000+0000")
    assert stale is False


@pytest.mark.asyncio
async def test_check_stale_equal_returns_false():
    ts = "2026-05-27T10:00:00.000+0000"
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_client = _make_get_mock(ts)
    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        stale = await client.check_stale("PROJ-1", ts)
    assert stale is False


@pytest.mark.asyncio
async def test_check_stale_empty_fetched_is_fresh():
    """No snapshot timestamp → treat as fresh (don't block the write)."""
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_client = _make_get_mock("2026-05-28T12:00:00.000+0000")
    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        stale = await client.check_stale("PROJ-1", "")
    assert stale is False
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_check_stale_jira_missing_updated_returns_false():
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_client = _make_get_mock(None)
    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        stale = await client.check_stale("PROJ-1", "2026-05-27T10:00:00.000+0000")
    assert stale is False
