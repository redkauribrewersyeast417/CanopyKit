from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from canopykit.event_adapter import AgentEventFeedConfig, EventAdapter, FeedSource


def _config(tmp_path):
    return AgentEventFeedConfig(
        base_url="http://canopy.test",
        api_key="test-key",
        agent_id="agent-1",
        data_dir=str(tmp_path),
        poll_interval_seconds=0,
    )


def _response(json_data, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    if status_code >= 400:
        error = requests.exceptions.HTTPError(response=resp)
        resp.raise_for_status.side_effect = error
    else:
        resp.raise_for_status.return_value = None
    return resp


@patch("canopykit.event_adapter.requests.get")
def test_probe_prefers_agent_scoped_feed(mock_get, tmp_path):
    mock_get.return_value = _response({"items": [], "next_after_seq": 0}, 200)
    adapter = EventAdapter(_config(tmp_path))

    source = adapter.probe_feed_source()

    assert source is FeedSource.AGENT_SCOPED
    assert adapter.feed_source is FeedSource.AGENT_SCOPED
    assert adapter.last_probe_result is not None
    assert adapter.last_probe_result.endpoint == adapter.AGENT_EVENTS_PATH


@patch("canopykit.event_adapter.requests.get")
def test_probe_falls_back_to_global_on_agent_404(mock_get, tmp_path):
    mock_get.side_effect = [
        _response({}, 404),
        _response({"items": [], "next_after_seq": 0}, 200),
    ]
    adapter = EventAdapter(_config(tmp_path))

    source = adapter.probe_feed_source()

    assert source is FeedSource.GLOBAL
    assert adapter.feed_source is FeedSource.GLOBAL
    assert adapter.last_probe_result is not None
    assert adapter.last_probe_result.fallback_reason == "agent_endpoint_not_available"


@patch("canopykit.event_adapter.requests.get")
def test_poll_uses_global_fallback_after_probe(mock_get, tmp_path):
    mock_get.side_effect = [
        _response({}, 404),
        _response({"items": [], "next_after_seq": 0}, 200),
        _response({"items": [{"seq": 1}], "next_after_seq": 1}, 200),
    ]
    adapter = EventAdapter(_config(tmp_path))

    items, next_seq = adapter.poll()

    assert adapter.feed_source is FeedSource.GLOBAL
    assert items == [{"seq": 1}]
    assert next_seq == 1


@patch("canopykit.event_adapter.requests.get")
def test_agent_scoped_404_during_fetch_switches_to_global(mock_get, tmp_path):
    mock_get.side_effect = [
        _response({"items": [], "next_after_seq": 0}, 200),  # probe preferred
        _response({}, 404),  # actual fetch fails
        _response({"items": [{"seq": 3}], "next_after_seq": 3}, 200),  # global retry
    ]
    adapter = EventAdapter(_config(tmp_path))

    items, next_seq = adapter.poll()

    assert adapter.feed_source is FeedSource.GLOBAL
    assert items == [{"seq": 3}]
    assert next_seq == 3


@patch("canopykit.event_adapter.requests.get")
def test_should_heartbeat_fallback_handles_zero_poll_interval(mock_get, tmp_path):
    mock_get.return_value = _response({"items": [], "next_after_seq": 0}, 200)
    adapter = EventAdapter(_config(tmp_path))
    adapter.probe_feed_source()
    adapter._consecutive_empty_polls = 30

    assert adapter.should_heartbeat_fallback() is True


@patch("canopykit.event_adapter.requests.get")
def test_probe_sets_error_class_on_auth_failure_401(mock_get, tmp_path):
    mock_get.return_value = _response({}, 401)
    adapter = EventAdapter(_config(tmp_path))

    source = adapter.probe_feed_source()

    assert source is FeedSource.UNKNOWN
    assert adapter.last_probe_result is not None
    assert adapter.last_probe_result.error_class == "http_401"
    assert adapter.last_probe_result.status_code == 401
    assert adapter.last_probe_result.fallback_reason == "agent_probe_failed"
    assert adapter.last_probe_result.active_feed_source == "unknown"


@patch("canopykit.event_adapter.requests.get")
def test_probe_sets_error_class_on_forbidden_403(mock_get, tmp_path):
    mock_get.return_value = _response({}, 403)
    adapter = EventAdapter(_config(tmp_path))

    source = adapter.probe_feed_source()

    assert source is FeedSource.UNKNOWN
    assert adapter.last_probe_result is not None
    assert adapter.last_probe_result.error_class == "http_403"
    assert adapter.last_probe_result.status_code == 403
    assert adapter.last_probe_result.fallback_reason == "agent_probe_failed"


@patch("canopykit.event_adapter.requests.get")
def test_probe_error_class_empty_when_agent_scoped_succeeds(mock_get, tmp_path):
    mock_get.return_value = _response({"items": [], "next_after_seq": 0}, 200)
    adapter = EventAdapter(_config(tmp_path))

    source = adapter.probe_feed_source()

    assert source is FeedSource.AGENT_SCOPED
    assert adapter.last_probe_result is not None
    assert adapter.last_probe_result.error_class == ""


@patch("canopykit.event_adapter.requests.get")
def test_probe_error_class_empty_when_global_fallback_succeeds(mock_get, tmp_path):
    mock_get.side_effect = [
        _response({}, 404),
        _response({"items": [], "next_after_seq": 0}, 200),
    ]
    adapter = EventAdapter(_config(tmp_path))

    source = adapter.probe_feed_source()

    assert source is FeedSource.GLOBAL
    assert adapter.last_probe_result is not None
    assert adapter.last_probe_result.error_class == ""
