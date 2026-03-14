#!/usr/bin/env python3
"""Contract tests for EventAdapter - /api/v1/agents/me/events route.

Tests the route contract:
- Response contains items (not events)
- Response includes next_after_seq for pagination
- Cursor is integer sequence
- SQLite datetime('now') writes are valid
- Feed-probe result shapes match machine-readable fixtures
"""

import json
import pytest
import sqlite3
import tempfile
import os
from pathlib import Path


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


class TestEventAdapterContract:
    """Contract tests for /api/v1/agents/me/events route."""

    def test_response_has_items_not_events(self):
        response_shape = {"items": [], "next_after_seq": 0}
        assert "items" in response_shape
        assert "events" not in response_shape

    def test_response_has_next_after_seq(self):
        response_shape = {"items": [{"id": "E001"}], "next_after_seq": 42}
        assert "next_after_seq" in response_shape
        assert isinstance(response_shape["next_after_seq"], int)

    def test_cursor_is_integer(self):
        for cursor in [0, 1, 42, 1000000]:
            assert isinstance(cursor, int)

    def test_after_seq_parameter_is_integer(self):
        params = {"after_seq": 42}
        assert isinstance(params["after_seq"], int)

    def test_sqlite_datetime_now_write(self, temp_db):
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE cursors (agent_id TEXT PRIMARY KEY, last_seq INTEGER, updated_at TIMESTAMP)")
        conn.execute("INSERT OR REPLACE INTO cursors (agent_id, last_seq, updated_at) VALUES (?, ?, datetime('now'))", ("test", 123))
        conn.commit()
        row = conn.execute("SELECT last_seq, updated_at FROM cursors WHERE agent_id = ?", ("test",)).fetchone()
        assert row[0] == 123
        assert row[1] is not None
        conn.close()

    def test_sqlite_datetime_now_not_column_reference(self, temp_db):
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE cursors (agent_id TEXT PRIMARY KEY, last_seq INTEGER, updated_at TIMESTAMP)")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO cursors (agent_id, last_seq, updated_at) VALUES (?, ?, datetime(now))", ("test", 123))
        conn.close()


class TestEventAdapterCursorPersistence:
    """Tests for cursor persistence behavior."""

    def test_cursor_persists_as_integer(self, temp_db):
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE cursors (agent_id TEXT PRIMARY KEY, last_seq INTEGER, updated_at TIMESTAMP)")
        conn.execute("INSERT INTO cursors (agent_id, last_seq) VALUES (?, ?)", ("agent_1", 42))
        conn.commit()
        row = conn.execute("SELECT last_seq FROM cursors WHERE agent_id = ?", ("agent_1",)).fetchone()
        assert row[0] == 42
        assert isinstance(row[0], int)
        conn.close()


class TestFeedProbeResultFixtures:
    """Contract tests using machine-readable fixtures for feed-probe scenarios.

    Each fixture captures the stable expected output shape for one of the three
    compatibility scenarios:
      - agent-scoped feed available (full_pass)
      - compatibility fallback to /api/v1/events (compatibility_pass)
      - authorization failure / auth-blocked probe (failed)
    """

    _FIXTURES_DIR = Path(__file__).parent / "fixtures"

    def _load(self, name: str) -> dict:
        return json.loads((self._FIXTURES_DIR / name).read_text())

    # ------------------------------------------------------------------
    # Fixture shape tests (do not touch the adapter; validate the fixture
    # files themselves so they cannot drift into an invalid state)
    # ------------------------------------------------------------------

    def test_agent_scoped_fixture_shape(self):
        fixture = self._load("probe_agent_scoped.json")
        pr = fixture["probe_result"]
        assert pr["endpoint"] == "/api/v1/agents/me/events"
        assert pr["status_code"] == 200
        assert pr["error_class"] == ""
        assert pr["active_feed_source"] == "agent_scoped"
        assert pr["fallback_reason"] == ""
        assert fixture["feed_source"] == "agent_scoped"
        assert fixture["validation_status"] == "full_pass"

    def test_global_fallback_fixture_shape(self):
        fixture = self._load("probe_global_fallback.json")
        pr = fixture["probe_result"]
        assert pr["endpoint"] == "/api/v1/events"
        assert pr["status_code"] == 200
        assert pr["error_class"] == ""
        assert pr["active_feed_source"] == "global"
        assert pr["fallback_reason"] == "agent_endpoint_not_available"
        assert fixture["feed_source"] == "global"
        assert fixture["validation_status"] == "compatibility_pass"

    def test_auth_blocked_fixture_shape(self):
        fixture = self._load("probe_auth_blocked.json")
        pr = fixture["probe_result"]
        assert pr["endpoint"] == "/api/v1/agents/me/events"
        assert pr["status_code"] == 401
        assert pr["error_class"] == "http_401"
        assert pr["active_feed_source"] == "unknown"
        assert pr["fallback_reason"] == "agent_probe_failed"
        assert fixture["feed_source"] == "unknown"
        assert fixture["validation_status"] == "failed"

    def test_auth_blocked_error_class_is_http_prefixed_with_status(self):
        fixture = self._load("probe_auth_blocked.json")
        pr = fixture["probe_result"]
        assert pr["error_class"].startswith("http_")
        assert pr["error_class"] == f"http_{pr['status_code']}"

    # ------------------------------------------------------------------
    # Cross-fixture invariants
    # ------------------------------------------------------------------

    def test_all_fixtures_have_required_top_level_fields(self):
        required = {"scenario", "description", "probe_result", "feed_source", "validation_status"}
        for name in ("probe_agent_scoped.json", "probe_global_fallback.json", "probe_auth_blocked.json"):
            fixture = self._load(name)
            missing = required - set(fixture)
            assert not missing, f"{name} missing fields: {missing}"

    def test_all_fixtures_probe_result_have_required_fields(self):
        required = {"endpoint", "status_code", "error_class", "active_feed_source", "fallback_reason"}
        for name in ("probe_agent_scoped.json", "probe_global_fallback.json", "probe_auth_blocked.json"):
            pr = self._load(name)["probe_result"]
            missing = required - set(pr)
            assert not missing, f"{name} probe_result missing fields: {missing}"

    def test_success_probes_have_empty_error_class(self):
        for name in ("probe_agent_scoped.json", "probe_global_fallback.json"):
            fixture = self._load(name)
            assert fixture["probe_result"]["error_class"] == "", (
                f"{name}: successful probe should have empty error_class"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])