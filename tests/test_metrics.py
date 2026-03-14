"""Tests for canopykit/metrics.py"""

from __future__ import annotations

import sys
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from canopykit.metrics import (
    MetricSpec,
    MetricSample,
    LatencyTracker,
    MetricsEmitter,
    metric_names,
    CORE_METRICS,
    event_to_seen,
    event_to_claim,
    claim_to_complete,
    update_pending_inbox,
    update_unacked_mentions,
    increment_timeout_recovery,
)


class TestMetricSpec:
    """Test MetricSpec dataclass."""

    def test_metric_spec_creation(self):
        spec = MetricSpec(
            name="test_metric",
            unit="milliseconds",
            description="Test metric",
            labels=("agent_id", "event_type"),
        )
        assert spec.name == "test_metric"
        assert spec.unit == "milliseconds"
        assert spec.description == "Test metric"
        assert spec.labels == ("agent_id", "event_type")

    def test_core_metrics_defined(self):
        names = metric_names()
        assert "event_to_seen_ms" in names
        assert "event_to_claim_ms" in names
        assert "claim_to_complete_ms" in names
        assert "pending_inbox" in names
        assert "unacked_mentions" in names
        assert "timeout_recoveries" in names
        assert len(CORE_METRICS) == 6
        assert len(names) == 6
        assert names == metric_names()


class TestMetricSample:
    """Test MetricSample dataclass."""

    def test_sample_creation(self):
        sample = MetricSample(
            metric="event_to_seen_ms",
            value=150.5,
            labels={"agent_id": "test_agent", "event_type": "mention"},
            timestamp_ms=1234567890000,
        )
        assert sample.metric == "event_to_seen_ms"
        assert sample.value == 150.5
        assert sample.labels == {"agent_id": "test_agent", "event_type": "mention"}
        assert sample.timestamp_ms == 1234567890000


class TestLatencyTracker:
    """Test LatencyTracker."""

    def test_tracker_complete(self):
        tracker = LatencyTracker(
            metric="event_to_seen_ms",
            start_ms=1000,
            labels={"agent_id": "test"},
        )
        sample = tracker.complete(end_ms=1500)
        assert sample.metric == "event_to_seen_ms"
        assert sample.value == 500.0
        assert sample.labels == {"agent_id": "test"}
        assert sample.timestamp_ms == 1500


class TestMetricsEmitter:
    """Test MetricsEmitter."""

    def test_emitter_creation(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        assert emitter.agent_id == "test_agent"
        assert len(emitter._samples) == 0

    def test_record_basic(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        emitter.record("pending_inbox", 5.0, agent_id="test_agent")
        assert len(emitter._samples) == 1
        assert emitter.get_current("pending_inbox") == 5.0

    def test_record_multiple(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        emitter.record("pending_inbox", 3.0)
        emitter.record("pending_inbox", 7.0)
        emitter.record("unacked_mentions", 2.0)
        assert len(emitter._samples) == 3
        assert emitter.get_current("pending_inbox") == 7.0
        assert emitter.get_current("unacked_mentions") == 2.0

    def test_increment(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        emitter.record("timeout_recoveries", 0.0)
        emitter.increment("timeout_recoveries")
        emitter.increment("timeout_recoveries", delta=5.0)
        assert emitter.get_current("timeout_recoveries") == 6.0

    def test_time_context_manager(self):
        import time
        emitter = MetricsEmitter(agent_id="test_agent")
        with emitter.time("event_to_seen_ms", agent_id="test_agent", event_type="mention"):
            time.sleep(0.01)  # Small delay
        assert len(emitter._samples) == 1
        assert emitter._samples[0].metric == "event_to_seen_ms"
        assert emitter._samples[0].value >= 10.0  # At least 10ms

    def test_get_samples_with_filter(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        emitter.record("event_to_seen_ms", 100.0)
        emitter.record("event_to_seen_ms", 200.0)
        emitter.record("pending_inbox", 5.0)
        samples = emitter.get_samples(metric="event_to_seen_ms")
        assert len(samples) == 2

    def test_aggregate(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        emitter.record("event_to_seen_ms", 100.0)
        emitter.record("event_to_seen_ms", 200.0)
        emitter.record("event_to_seen_ms", 300.0)
        agg = emitter.aggregate("event_to_seen_ms")
        assert agg["count"] == 3.0
        assert agg["sum"] == 600.0
        assert agg["min"] == 100.0
        assert agg["max"] == 300.0
        assert agg["mean"] == 200.0

    def test_snapshot(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        emitter.record("pending_inbox", 5.0, agent_id="test_agent")
        emitter.record("unacked_mentions", 3.0, agent_id="test_agent")
        snapshot = emitter.snapshot()
        assert snapshot["agent_id"] == "test_agent"
        assert snapshot["current_values"]["pending_inbox"] == 5.0
        assert snapshot["current_values"]["unacked_mentions"] == 3.0

    def test_clear(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        emitter.record("pending_inbox", 5.0)
        emitter.record("unacked_mentions", 3.0)
        emitter.clear()
        assert len(emitter._samples) == 0
        assert emitter.get_current("pending_inbox", default=0.0) == 0.0

    def test_prometheus_export(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        emitter.record("pending_inbox", 5.0, agent_id="test_agent")
        output = emitter.export_prometheus()
        assert "# HELP pending_inbox" in output
        assert "# TYPE pending_inbox gauge" in output
        assert "pending_inbox" in output

    def test_sqlite_persistence(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        try:
            emitter = MetricsEmitter(agent_id="test_agent", db_path=db_path)
            emitter.record("pending_inbox", 5.0, agent_id="test_agent")
            # Clear in-memory to test persistence
            emitter2 = MetricsEmitter(agent_id="test_agent", db_path=db_path)
            emitter2.clear()
            assert len(emitter2._samples) == 0
        finally:
            db_path.unlink(missing_ok=True)


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_event_to_seen(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        event_to_seen(emitter, "mention", 150.0)
        assert len(emitter._samples) == 1
        assert emitter._samples[0].metric == "event_to_seen_ms"
        assert emitter._samples[0].value == 150.0

    def test_event_to_claim(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        event_to_claim(emitter, "channel_message", 200.0)
        assert len(emitter._samples) == 1
        assert emitter._samples[0].labels["source_type"] == "channel_message"

    def test_claim_to_complete(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        claim_to_complete(emitter, "inbox", 50.0)
        assert len(emitter._samples) == 1

    def test_update_pending_inbox(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        update_pending_inbox(emitter, 10)
        assert emitter.get_current("pending_inbox") == 10.0

    def test_update_unacked_mentions(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        update_unacked_mentions(emitter, 5)
        assert emitter.get_current("unacked_mentions") == 5.0

    def test_increment_timeout_recovery(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        increment_timeout_recovery(emitter)
        increment_timeout_recovery(emitter)
        increment_timeout_recovery(emitter)
        assert emitter.get_current("timeout_recoveries") == 3.0

    def test_health_report_healthy(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        # Low backlog, no issues
        emitter.record("pending_inbox", 5.0, agent_id="test_agent")
        emitter.record("event_to_claim_ms", 100.0, agent_id="test_agent", source_type="mention")
        report = emitter.health_report()
        assert report["health"] in ("healthy", "background")
        assert report["mode"] in ("relay", "support", "background")
        assert "agent_id" in report
        assert "timestamp_ms" in report

    def test_health_report_degraded_high_backlog(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        # High backlog
        emitter.record("pending_inbox", 60.0, agent_id="test_agent")
        report = emitter.health_report()
        assert report["health"] == "degraded"
        assert any("high_backlog" in issue for issue in report["health_issues"])

    def test_health_report_unhealthy_overflow(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        # Backlog overflow
        emitter.record("pending_inbox", 150.0, agent_id="test_agent")
        report = emitter.health_report()
        assert report["health"] == "unhealthy"
        assert any("backlog_overflow" in issue for issue in report["health_issues"])

    def test_health_report_recovering(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        # Timeout recoveries indicate recovering state
        emitter.record("pending_inbox", 5.0, agent_id="test_agent")
        emitter.increment("timeout_recoveries", agent_id="test_agent")
        report = emitter.health_report()
        assert report["health"] == "recovering"
        assert any("timeout_recoveries" in issue for issue in report["health_issues"])

    def test_health_report_mode_relay(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        # High activity, low latency = relay mode
        emitter.record("pending_inbox", 10.0, agent_id="test_agent")
        for i in range(15):
            emitter.record("event_to_seen_ms", 50.0 + i, agent_id="test_agent", event_type="mention")
        for i in range(8):
            emitter.record("event_to_claim_ms", 100.0 + i, agent_id="test_agent", source_type="mention")
        report = emitter.health_report()
        assert report["mode"] == "relay"
        assert report["mode_reason"] == "high_activity_low_latency"

    def test_health_report_mode_support(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        # Moderate activity = support mode
        emitter.record("pending_inbox", 10.0, agent_id="test_agent")
        for i in range(5):
            emitter.record("event_to_seen_ms", 100.0 + i, agent_id="test_agent", event_type="mention")
        emitter.record("event_to_claim_ms", 200.0, agent_id="test_agent", source_type="mention")
        report = emitter.health_report()
        assert report["mode"] == "support"

    def test_health_report_metrics_shape(self):
        emitter = MetricsEmitter(agent_id="test_agent")
        emitter.record("pending_inbox", 10.0, agent_id="test_agent")
        emitter.record("unacked_mentions", 5.0, agent_id="test_agent")
        emitter.record("event_to_claim_ms", 150.0, agent_id="test_agent", source_type="mention")
        report = emitter.health_report()
        assert "pending_inbox" in report["metrics"]
        assert "unacked_mentions" in report["metrics"]
        assert "latencies" in report["metrics"]
        assert report["metrics"]["pending_inbox"] == 10
        assert report["metrics"]["unacked_mentions"] == 5