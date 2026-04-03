"""Track 4 verification: JiraClient extensions + push.py resolver."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from src.integrations.jira.client import JiraClient


# ---------------------------------------------------------------------------
# JiraClient — property and method URL verification
# ---------------------------------------------------------------------------

def test_agile_base_url():
    client = JiraClient(cloud_id="abc123", access_token="tok")
    assert client.agile_base_url == "https://api.atlassian.com/ex/jira/abc123/rest/agile/1.0"


@pytest.mark.asyncio
async def test_create_sprint_calls_correct_url():
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"id": 42, "self": "https://jira.example.com/sprint/42"})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        result = await client.create_sprint("board-1", "Sprint 1", "2026-04-01", "2026-04-14")

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == "https://api.atlassian.com/ex/jira/cid/rest/agile/1.0/sprint"
    assert call_args[1]["json"]["originBoardId"] == "board-1"
    assert call_args[1]["json"]["name"] == "Sprint 1"
    assert result == {"id": 42, "self": "https://jira.example.com/sprint/42"}


@pytest.mark.asyncio
async def test_move_issues_to_sprint_calls_correct_url():
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        await client.move_issues_to_sprint(42, ["PROJ-1", "PROJ-2"])

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == "https://api.atlassian.com/ex/jira/cid/rest/agile/1.0/sprint/42/issue"
    assert call_args[1]["json"]["issues"] == ["PROJ-1", "PROJ-2"]


@pytest.mark.asyncio
async def test_assign_issue_calls_correct_url():
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.put = AsyncMock(return_value=mock_response)

    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        await client.assign_issue("PROJ-1", "jira-account-abc")

    mock_client.put.assert_called_once()
    call_args = mock_client.put.call_args
    assert call_args[0][0] == "https://api.atlassian.com/ex/jira/cid/rest/api/3/issue/PROJ-1/assignee"
    assert call_args[1]["json"]["accountId"] == "jira-account-abc"


# ---------------------------------------------------------------------------
# push.py — resolve_jira_account_id resolver
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_jira_account_id_match():
    """Returns jira_account_id when developer email matches a team member."""
    from src.integrations.jira.push import resolve_jira_account_id

    dev_id = str(uuid.uuid4())
    team_id = str(uuid.uuid4())

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value="jira-acct-xyz")
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await resolve_jira_account_id(dev_id, team_id, mock_db)

    assert result == "jira-acct-xyz"
    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_jira_account_id_no_match():
    """Returns None when no matching team member found."""
    from src.integrations.jira.push import resolve_jira_account_id

    dev_id = str(uuid.uuid4())
    team_id = str(uuid.uuid4())

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await resolve_jira_account_id(dev_id, team_id, mock_db)

    assert result is None
    mock_db.execute.assert_called_once()
