from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from canopykit import AgentMode, CoordinationSnapshot
from canopykit.inbox_supervisor import CanopyInboxSupervisor, InboxSupervisorConfig


def _config() -> InboxSupervisorConfig:
    return InboxSupervisorConfig(
        base_url="http://canopy.test",
        api_key="test-key",
        request_timeout_seconds=4.0,
        inbox_limit=25,
    )


def _response(json_data, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


@patch("canopykit.inbox_supervisor.requests.get")
def test_snapshot_uses_live_canopy_status_fields(mock_get):
    mock_get.side_effect = [
        _response(
            {
                "poll_hint_seconds": 5,
                "unacked_mentions": 3,
                "workspace_event_seq": 81,
                "mode": "relay_grade",
            }
        ),
        _response(
            {
                "items": [
                    {"id": "INB1", "status": "pending"},
                    {"id": "INB2", "status": "seen"},
                    {"id": "INB3", "status": "completed"},
                ]
            }
        ),
    ]
    sup = CanopyInboxSupervisor(_config())

    snapshot = sup.snapshot()

    assert isinstance(snapshot, CoordinationSnapshot)
    assert snapshot.wake_source == "inbox"
    assert snapshot.canopy_poll_interval_seconds == 5
    assert snapshot.blind_window_seconds == 5
    assert snapshot.pending_inbox == 2
    assert snapshot.unacked_mentions == 3
    assert snapshot.last_event_cursor_seen == 81
    assert snapshot.mode == AgentMode.RELAY_GRADE


@patch("canopykit.inbox_supervisor.requests.get")
def test_snapshot_defaults_mode_to_background_when_missing(mock_get):
    mock_get.side_effect = [
        _response({"poll_hint_seconds": 5, "unacked_mentions": 0}),
        _response({"items": []}),
    ]

    snapshot = CanopyInboxSupervisor(_config()).snapshot()

    assert snapshot.mode == AgentMode.BACKGROUND
    assert snapshot.wake_source == "heartbeat"


@patch("canopykit.inbox_supervisor.requests.patch")
def test_mark_seen_uses_status_payload(mock_patch):
    mock_patch.return_value = _response({})
    sup = CanopyInboxSupervisor(_config())

    result = sup.mark_seen("INB123")

    assert mock_patch.call_count == 1
    assert mock_patch.call_args.args[0] == "http://canopy.test/api/v1/agents/me/inbox/INB123"
    assert mock_patch.call_args.kwargs["json"] == {"status": "seen"}
    assert mock_patch.call_args.kwargs["timeout"] == 4.0
    assert result.applied is True


@patch("canopykit.inbox_supervisor.requests.patch")
def test_mark_seen_returns_retryable_result_on_rate_limit(mock_patch):
    response = _response({}, status_code=429)
    response.raise_for_status.side_effect = requests.HTTPError("rate limited", response=response)
    mock_patch.return_value = response

    result = CanopyInboxSupervisor(_config()).mark_seen("INB123")

    assert result.applied is False
    assert result.retryable is True
    assert result.status_code == 429
    assert result.error_class == "HTTPError"


@patch("canopykit.inbox_supervisor.requests.patch")
def test_mark_completed_requires_completion_ref(mock_patch):
    sup = CanopyInboxSupervisor(_config())

    with pytest.raises(ValueError):
        sup.mark_completed("INB123", {})

    assert mock_patch.call_count == 0


@patch("canopykit.inbox_supervisor.requests.patch")
def test_mark_completed_uses_status_and_completion_ref(mock_patch):
    mock_patch.return_value = _response({})
    sup = CanopyInboxSupervisor(_config())

    sup.mark_completed("INB123", {"message_id": "M1"})

    assert mock_patch.call_count == 1
    assert mock_patch.call_args.kwargs["json"] == {
        "status": "completed",
        "completion_ref": {"message_id": "M1"},
    }


@patch("canopykit.inbox_supervisor.requests.get")
def test_snapshot_sends_api_key_and_limit(mock_get):
    mock_get.side_effect = [
        _response({"poll_hint_seconds": 5, "unacked_mentions": 0}),
        _response({"items": []}),
    ]
    sup = CanopyInboxSupervisor(_config())

    sup.snapshot()

    heartbeat_call, inbox_call = mock_get.call_args_list
    assert heartbeat_call.kwargs["headers"]["X-API-Key"] == "test-key"
    assert inbox_call.kwargs["headers"]["X-API-Key"] == "test-key"
    assert inbox_call.kwargs["params"] == {"limit": 25}
