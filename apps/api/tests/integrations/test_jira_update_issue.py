"""Wave 0 / SB-3 — JiraClient.update_issue PUT /rest/api/3/issue/{key}.

Mocks ``httpx.AsyncClient`` the same way as ``tests/test_track4_jira_push.py``
(no real network; no respx dependency required).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.integrations.jira.client import JiraClient, _plain_text_to_adf


def _make_mock_client(status_code: int = 204, body_text: str = ""):
    """Build an httpx.AsyncClient mock whose .put() returns the given status."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.text = body_text
    mock_response.is_success = 200 <= status_code < 300
    if mock_response.is_success:
        mock_response.raise_for_status = MagicMock()
    else:
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"{status_code}", request=MagicMock(), response=mock_response
            )
        )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.put = AsyncMock(return_value=mock_response)
    return mock_client, mock_response


# ---------------------------------------------------------------------------
# _plain_text_to_adf helper
# ---------------------------------------------------------------------------

def test_plain_text_to_adf_minimal_envelope():
    adf = _plain_text_to_adf("Hello world")
    assert adf == {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Hello world"}],
            }
        ],
    }


# ---------------------------------------------------------------------------
# update_issue — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_issue_happy_path_title_description_story_points():
    """summary + plain-text description + story points → PUT with ADF-wrapped desc."""
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_client, _ = _make_mock_client(status_code=204)

    fields = {
        "summary": "New title",
        "description": "Plain text description.",
        "customfield_10016": 5,  # story points
    }

    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        result = await client.update_issue("PROJ-42", fields)

    mock_client.put.assert_called_once()
    call_args = mock_client.put.call_args
    assert call_args[0][0] == "https://api.atlassian.com/ex/jira/cid/rest/api/3/issue/PROJ-42"

    body = call_args[1]["json"]
    assert set(body.keys()) == {"fields"}
    sent = body["fields"]

    assert sent["summary"] == "New title"
    assert sent["customfield_10016"] == 5
    # Description string must be wrapped in ADF.
    assert sent["description"] == _plain_text_to_adf("Plain text description.")

    # Headers carry auth + JSON content type.
    headers = call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Content-Type"] == "application/json"

    # Return value reflects the transformed payload.
    assert result["description"] == _plain_text_to_adf("Plain text description.")
    assert result["summary"] == "New title"
    assert result["customfield_10016"] == 5


@pytest.mark.asyncio
async def test_update_issue_204_no_content_returns_payload():
    """Jira returns 204 on success; method must not raise and should return fields."""
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_client, _ = _make_mock_client(status_code=204)

    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        result = await client.update_issue("PROJ-1", {"summary": "x"})

    assert result == {"summary": "x"}


# ---------------------------------------------------------------------------
# update_issue — error path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_issue_4xx_raises_http_status_error():
    """Non-2xx response surfaces as HTTPStatusError (mirrors assign_issue)."""
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_client, _ = _make_mock_client(status_code=400, body_text="bad fields")

    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.HTTPStatusError):
            await client.update_issue("PROJ-1", {"summary": "x"})


# ---------------------------------------------------------------------------
# update_issue — description pass-through
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_issue_description_dict_passed_through_unchanged():
    """If caller supplies an ADF dict for description, do not re-wrap it."""
    client = JiraClient(cloud_id="cid", access_token="tok")
    mock_client, _ = _make_mock_client(status_code=204)

    prebuilt_adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Already "},
                    {"type": "text", "text": "ADF", "marks": [{"type": "strong"}]},
                ],
            }
        ],
    }

    with patch("src.integrations.jira.client.httpx.AsyncClient", return_value=mock_client):
        await client.update_issue("PROJ-7", {"description": prebuilt_adf})

    sent = mock_client.put.call_args[1]["json"]["fields"]
    assert sent["description"] is prebuilt_adf or sent["description"] == prebuilt_adf
