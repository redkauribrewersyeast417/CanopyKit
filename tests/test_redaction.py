from __future__ import annotations

import pytest

from canopykit.redaction import REDACTED_PLACEHOLDER, redact_secrets


# ---------------------------------------------------------------------------
# Basic sensitive-key detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "API_KEY",
        "Api_Key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "secret",
        "client_secret",
        "my_secret_value",
        "password",
        "passwd",
        "user_password",
        "authorization",
        "Authorization",
        "bearer",
        "Bearer",
        "access_key",
        "AWS_ACCESS_KEY",
    ],
)
def test_sensitive_key_is_redacted(key):
    result = redact_secrets({key: "super-secret-value"})
    assert result[key] == REDACTED_PLACEHOLDER


# ---------------------------------------------------------------------------
# Non-sensitive fields must pass through unchanged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "key",
    [
        "agent_id",
        "base_url",
        "timestamp_ms",
        "status",
        "health",
        "mode",
        "cycle",
        "cursor",
        "event_type",
        "inbox_id",
        "channel_id",
        "feed_source",
        "product_name",
    ],
)
def test_non_sensitive_key_is_preserved(key):
    value = "some-value-123"
    result = redact_secrets({key: value})
    assert result[key] == value


# ---------------------------------------------------------------------------
# Nested structures
# ---------------------------------------------------------------------------

def test_nested_dict_sensitive_key_is_redacted():
    obj = {
        "outer": "safe",
        "credentials": {
            "api_key": "abc123",
            "user": "alice",
        },
    }
    result = redact_secrets(obj)
    assert result["outer"] == "safe"
    assert result["credentials"]["user"] == "alice"
    assert result["credentials"]["api_key"] == REDACTED_PLACEHOLDER


def test_list_of_dicts_is_recursed():
    obj = [
        {"agent_id": "a1", "token": "tok1"},
        {"agent_id": "a2", "token": "tok2"},
    ]
    result = redact_secrets(obj)
    assert result[0]["agent_id"] == "a1"
    assert result[0]["token"] == REDACTED_PLACEHOLDER
    assert result[1]["agent_id"] == "a2"
    assert result[1]["token"] == REDACTED_PLACEHOLDER


def test_deeply_nested_structure():
    obj = {
        "level1": {
            "level2": {
                "level3": {
                    "secret": "hidden",
                    "visible": "ok",
                }
            }
        }
    }
    result = redact_secrets(obj)
    assert result["level1"]["level2"]["level3"]["secret"] == REDACTED_PLACEHOLDER
    assert result["level1"]["level2"]["level3"]["visible"] == "ok"


# ---------------------------------------------------------------------------
# Original object is not mutated
# ---------------------------------------------------------------------------

def test_original_dict_is_not_mutated():
    original = {"api_key": "my-key", "agent_id": "a1"}
    _ = redact_secrets(original)
    assert original["api_key"] == "my-key"


def test_original_list_is_not_mutated():
    original = [{"password": "pw1"}, {"password": "pw2"}]
    _ = redact_secrets(original)
    assert original[0]["password"] == "pw1"


# ---------------------------------------------------------------------------
# Scalar / non-dict-list pass-through
# ---------------------------------------------------------------------------

def test_scalar_string_is_unchanged():
    assert redact_secrets("plain text") == "plain text"


def test_scalar_int_is_unchanged():
    assert redact_secrets(42) == 42


def test_none_is_unchanged():
    assert redact_secrets(None) is None


def test_empty_dict_is_unchanged():
    assert redact_secrets({}) == {}


def test_empty_list_is_unchanged():
    assert redact_secrets([]) == []


# ---------------------------------------------------------------------------
# Realistic evidence/status payload shapes
# ---------------------------------------------------------------------------

def test_health_report_shape():
    """Simulate a MetricsEmitter health_report dict – non-sensitive fields intact."""
    report = {
        "agent_id": "agent-xyz",
        "timestamp_ms": 1700000000000,
        "health": "healthy",
        "mode": "background",
        "mode_reason": "low_activity",
        "health_issues": [],
        "metrics": {
            "pending_inbox": 3,
            "unacked_mentions": 0,
            "timeout_recoveries": 0,
            "recent_activity": True,
            "latencies": {},
        },
        "sample_count": 10,
    }
    result = redact_secrets(report)
    assert result["agent_id"] == "agent-xyz"
    assert result["health"] == "healthy"
    assert result["metrics"]["pending_inbox"] == 3


def test_print_config_redacts_api_key():
    """Simulate CanopyKitConfig.to_dict() output used by print-config."""
    config_dict = {
        "base_url": "http://localhost:7770",
        "api_key": "sk-live-ABCDEFGHIJ",
        "event_poll_interval_seconds": 15,
        "inbox_limit": 50,
    }
    result = redact_secrets(config_dict)
    assert result["api_key"] == REDACTED_PLACEHOLDER
    assert result["base_url"] == "http://localhost:7770"
    assert result["event_poll_interval_seconds"] == 15


def test_shadow_selftest_result_no_false_positives():
    """Ensure typical shadow selftest fields are not incorrectly redacted."""
    result = {
        "agent_id": "agent-abc",
        "base_url": "http://canopy.example",
        "feed_probe": {
            "feed_source": "agent_scoped",
            "endpoint": "/api/v1/events",
            "status_code": 200,
            "error_class": "",
            "fallback_reason": "",
        },
        "validation": {
            "status": "full_pass",
            "full_pass": True,
            "blocking_gaps": [],
            "warnings": [],
        },
    }
    redacted = redact_secrets(result)
    assert redacted["agent_id"] == "agent-abc"
    assert redacted["feed_probe"]["feed_source"] == "agent_scoped"
    assert redacted["validation"]["status"] == "full_pass"


def test_run_status_with_nested_token_in_payload():
    """Token value nested inside a queue payload item is redacted."""
    status = {
        "agent_id": "agent-1",
        "cycle": 1,
        "queue": {
            "actionable_count": 1,
            "recent_items": [
                {
                    "work_key": "inbox:123",
                    "payload": {"authorization": "Bearer tok-xyz", "task": "review"},
                }
            ],
        },
    }
    result = redact_secrets(status)
    payload = result["queue"]["recent_items"][0]["payload"]
    assert payload["authorization"] == REDACTED_PLACEHOLDER
    assert payload["task"] == "review"
    assert result["agent_id"] == "agent-1"
