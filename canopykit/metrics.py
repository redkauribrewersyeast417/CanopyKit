"""Coordination metrics vocabulary for CanopyKit.

This module provides:
- Metric specifications for CanopyKit coordination metrics
- MetricsEmitter implementation for recording and exporting metrics
- Timing utilities for latency measurement
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True, slots=True)
class MetricSpec:
    name: str
    unit: str
    description: str
    labels: tuple[str, ...]
    metric_type: str = "gauge"


CORE_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        name="event_to_seen_ms",
        unit="milliseconds",
        description="Latency from event cursor visibility to inbox item marked seen.",
        labels=("agent_id", "event_type"),
    ),
    MetricSpec(
        name="event_to_claim_ms",
        unit="milliseconds",
        description="Latency from event cursor visibility to successful claim.",
        labels=("agent_id", "source_type"),
    ),
    MetricSpec(
        name="claim_to_complete_ms",
        unit="milliseconds",
        description="Latency from successful claim to completion with evidence.",
        labels=("agent_id", "source_type"),
    ),
    MetricSpec(
        name="pending_inbox",
        unit="count",
        description="Current pending plus seen actionable inbox items.",
        labels=("agent_id",),
    ),
    MetricSpec(
        name="unacked_mentions",
        unit="count",
        description="Current unacknowledged mention count.",
        labels=("agent_id",),
    ),
    MetricSpec(
        name="timeout_recoveries",
        unit="count",
        description="Count of work items acquired by takeover after timeout.",
        labels=("agent_id",),
        metric_type="counter",
    ),
)


def metric_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in CORE_METRICS)


@dataclass(slots=True)
class MetricSample:
    """A single metric sample with value and labels."""
    metric: str
    value: float
    labels: Dict[str, str]
    timestamp_ms: int


@dataclass(slots=True)
class LatencyTracker:
    """Tracks latency measurements with start/end timestamps."""
    metric: str
    start_ms: int
    labels: Dict[str, str]

    def complete(self, end_ms: Optional[int] = None) -> MetricSample:
        """Complete the latency measurement and return the sample."""
        end = end_ms or int(time.time() * 1000)
        elapsed = end - self.start_ms
        return MetricSample(
            metric=self.metric,
            value=float(elapsed),
            labels=self.labels,
            timestamp_ms=end,
        )


class MetricsEmitter:
    """Concrete MetricsEmitter implementation for CanopyKit.

    Provides:
    - In-memory metric recording with optional SQLite persistence
    - Latency timing utilities via context managers
    - Snapshot export for operator visibility
    - Aggregation for runtime health reporting

    Usage:
        emitter = MetricsEmitter(agent_id="my_agent")

        # Record a single value
        emitter.record("pending_inbox", 5.0, agent_id="my_agent")

        # Time an operation
        with emitter.time("event_to_seen_ms", agent_id="my_agent", event_type="mention"):
            # ... do work ...
            pass

        # Get a snapshot
        snapshot = emitter.snapshot()
    """

    def __init__(
        self,
        agent_id: str,
        db_path: Optional[Path] = None,
        max_samples: int = 10000,
    ) -> None:
        self.agent_id = agent_id
        self._db_path = db_path
        self._max_samples = max_samples
        self._samples: List[MetricSample] = []
        self._current_values: Dict[str, float] = {}
        self._labels_index: Dict[str, Dict[Tuple[Tuple[str, str], ...], float]] = {}

        if db_path:
            self._init_db(db_path)

    def _init_db(self, path: Path) -> None:
        """Initialize SQLite persistence layer."""
        conn = sqlite3.connect(str(path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metric_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric TEXT NOT NULL,
                value REAL NOT NULL,
                labels TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_metric ON metric_samples(metric)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON metric_samples(timestamp_ms)")
        conn.commit()
        conn.close()

    def record(self, metric: str, value: float, **labels: Any) -> None:
        """Record a coordination metric sample."""
        # Normalize labels to strings
        label_dict = {k: str(v) for k, v in labels.items()}

        sample = MetricSample(
            metric=metric,
            value=value,
            labels=label_dict,
            timestamp_ms=int(time.time() * 1000),
        )

        self._samples.append(sample)
        self._current_values[metric] = value

        # Update labeled index for aggregation
        label_key = tuple(sorted(label_dict.items()))
        if metric not in self._labels_index:
            self._labels_index[metric] = {}
        self._labels_index[metric][label_key] = value

        # Persist if db configured
        if self._db_path:
            self._persist_sample(sample)

        # Trim if over limit
        if len(self._samples) > self._max_samples:
            self._samples = self._samples[-self._max_samples:]

    def _persist_sample(self, sample: MetricSample) -> None:
        """Persist a sample to SQLite."""
        try:
            import json
            conn = sqlite3.connect(str(self._db_path))
            conn.execute(
                "INSERT INTO metric_samples (metric, value, labels, timestamp_ms) VALUES (?, ?, ?, ?)",
                (sample.metric, sample.value, json.dumps(sample.labels), sample.timestamp_ms),
            )
            conn.commit()
            conn.close()
        except Exception:
            # Fail silently - metrics should not crash the runtime
            pass

    @contextmanager
    def time(self, metric: str, **labels: Any) -> Iterator[LatencyTracker]:
        """Context manager for timing operations.

        Usage:
            with emitter.time("event_to_seen_ms", agent_id="my_agent"):
                # ... timed operation ...
        """
        tracker = LatencyTracker(
            metric=metric,
            start_ms=int(time.time() * 1000),
            labels={k: str(v) for k, v in labels.items()},
        )
        try:
            yield tracker
        finally:
            sample = tracker.complete()
            self.record(metric, sample.value, **labels)

    def increment(self, metric: str, delta: float = 1.0, **labels: Any) -> None:
        """Increment a counter metric."""
        current = self._current_values.get(metric, 0.0)
        self.record(metric, current + delta, **labels)

    def get_current(self, metric: str, default: float = 0.0) -> float:
        """Get the current value of a metric."""
        return self._current_values.get(metric, default)

    def get_samples(self, metric: Optional[str] = None, limit: int = 100) -> List[MetricSample]:
        """Get recent samples, optionally filtered by metric name."""
        if metric:
            return [s for s in self._samples[-limit:] if s.metric == metric]
        return self._samples[-limit:]

    def aggregate(
        self,
        metric: str,
        window_ms: Optional[int] = None,
        labels: Optional[Dict[str, str]] = None,
    ) -> Dict[str, float]:
        """Aggregate samples for a metric.

        Returns:
            Dict with count, sum, min, max, mean.
        """
        now_ms = int(time.time() * 1000)
        samples = [s for s in self._samples if s.metric == metric]

        if window_ms:
            cutoff = now_ms - window_ms
            samples = [s for s in samples if s.timestamp_ms >= cutoff]

        if labels:
            samples = [
                s for s in samples
                if all(s.labels.get(k) == v for k, v in labels.items())
            ]

        if not samples:
            return {"count": 0.0, "sum": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}

        values = [s.value for s in samples]
        return {
            "count": float(len(values)),
            "sum": sum(values),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        }

    def snapshot(self) -> Dict[str, Any]:
        """Return a runtime metrics snapshot for operator visibility.

        Includes:
        - Current counter values
        - Recent latency aggregates
        - Timestamp
        """
        now_ms = int(time.time() * 1000)

        # Aggregate latencies over last 5 minutes
        window = 5 * 60 * 1000

        latencies = {}
        for metric_name in ("event_to_seen_ms", "event_to_claim_ms", "claim_to_complete_ms"):
            agg = self.aggregate(metric_name, window_ms=window)
            if agg["count"] > 0:
                latencies[metric_name] = {
                    "p50_approx": agg["mean"],
                    "min": agg["min"],
                    "max": agg["max"],
                    "count": int(agg["count"]),
                }

        return {
            "agent_id": self.agent_id,
            "timestamp_ms": now_ms,
            "current_values": {
                "pending_inbox": self.get_current("pending_inbox", 0.0),
                "unacked_mentions": self.get_current("unacked_mentions", 0.0),
                "timeout_recoveries": self.get_current("timeout_recoveries", 0.0),
            },
            "latencies": latencies,
            "sample_count": len(self._samples),
        }

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []

        for spec in CORE_METRICS:
            lines.append(f"# HELP {spec.name} {spec.description}")
            lines.append(f"# TYPE {spec.name} {spec.metric_type}")

            if spec.name in self._labels_index:
                for label_tuple, value in self._labels_index[spec.name].items():
                    if label_tuple:
                        label_str = ",".join(f'{k}="{v}"' for k, v in label_tuple)
                        lines.append(f"{spec.name}{{{label_str}}} {value}")
                    else:
                        lines.append(f"{spec.name} {value}")

        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all samples from memory."""
        self._samples.clear()
        self._current_values.clear()
        self._labels_index.clear()

    def health_report(self) -> Dict[str, Any]:
        """
        Generate a health report for operator visibility and mode classification.

        Classifies agent health into:
        - healthy: No issues, backlog under ceiling
        - degraded: Elevated latencies or backlog approaching ceiling
        - recovering: Recent errors or timeouts, but activity resuming
        - unhealthy: High backlog, persistent errors, or long inactivity

        Mode classification based on activity:
        - relay: High activity, low latency, reliable claim completion
        - support: Moderate activity, acceptable latency
        - background: Low activity, infrequent claims

        Returns:
            Dict with health status, mode classification, and key metrics
        """
        now_ms = int(time.time() * 1000)
        window_ms = 5 * 60 * 1000  # 5 minute window

        # Get current counters
        pending = self.get_current("pending_inbox", 0.0)
        unacked = self.get_current("unacked_mentions", 0.0)
        timeout_recoveries = self.get_current("timeout_recoveries", 0.0)

        # Aggregate latencies
        seen_agg = self.aggregate("event_to_seen_ms", window_ms=window_ms)
        claim_agg = self.aggregate("event_to_claim_ms", window_ms=window_ms)
        complete_agg = self.aggregate("claim_to_complete_ms", window_ms=window_ms)

        # Classification thresholds
        BACKLOG_CEILING = 100
        HIGH_BACKLOG = 50
        LATENCY_WARNING_MS = 5000  # 5 seconds
        LATENCY_CRITICAL_MS = 30000  # 30 seconds
        INACTIVITY_WARNING_MS = 10 * 60 * 1000  # 10 minutes

        # Determine health status
        health = "healthy"
        health_issues = []

        # Check backlog
        if pending > BACKLOG_CEILING:
            health = "unhealthy"
            health_issues.append(f"backlog_overflow:{int(pending)}")
        elif pending > HIGH_BACKLOG:
            health = "degraded"
            health_issues.append(f"high_backlog:{int(pending)}")

        # Check latencies
        if claim_agg["count"] > 0:
            if claim_agg["mean"] > LATENCY_CRITICAL_MS:
                health = "unhealthy"
                health_issues.append(f"critical_latency:{int(claim_agg['mean'])}ms")
            elif claim_agg["mean"] > LATENCY_WARNING_MS:
                if health == "healthy":
                    health = "degraded"
                health_issues.append(f"elevated_latency:{int(claim_agg['mean'])}ms")

        # Check timeout recoveries (sign of degraded state)
        if timeout_recoveries > 0:
            if health == "healthy":
                health = "recovering"
            health_issues.append(f"timeout_recoveries:{int(timeout_recoveries)}")

        # Check for inactivity (no latency samples in window)
        recent_activity = (
            seen_agg["count"] > 0 or
            claim_agg["count"] > 0 or
            complete_agg["count"] > 0
        )
        if not recent_activity:
            if health == "healthy":
                # Check for any samples at all
                if len(self._samples) == 0:
                    health = "background"  # New or inactive agent
                else:
                    # Check last sample timestamp
                    last_sample = self._samples[-1] if self._samples else None
                    if last_sample and (now_ms - last_sample.timestamp_ms) > INACTIVITY_WARNING_MS:
                        health = "degraded"
                        health_issues.append("inactivity_detected")

        # Determine mode classification
        mode = "background"
        mode_reason = "low_activity"

        if recent_activity:
            if seen_agg["count"] >= 10 and claim_agg["count"] >= 5:
                # High activity - check quality
                if claim_agg["mean"] < LATENCY_WARNING_MS and timeout_recoveries < 3:
                    mode = "relay"
                    mode_reason = "high_activity_low_latency"
                else:
                    mode = "support"
                    mode_reason = "high_activity_elevated_latency"
            elif seen_agg["count"] >= 3 or claim_agg["count"] >= 1:
                mode = "support"
                mode_reason = "moderate_activity"

        return {
            "agent_id": self.agent_id,
            "timestamp_ms": now_ms,
            "health": health,
            "mode": mode,
            "mode_reason": mode_reason,
            "health_issues": health_issues,
            "metrics": {
                "pending_inbox": int(pending),
                "unacked_mentions": int(unacked),
                "timeout_recoveries": int(timeout_recoveries),
                "recent_activity": recent_activity,
                "latencies": {
                    "event_to_seen_ms": {
                        "count": int(seen_agg["count"]),
                        "mean_ms": seen_agg["mean"],
                    } if seen_agg["count"] > 0 else None,
                    "event_to_claim_ms": {
                        "count": int(claim_agg["count"]),
                        "mean_ms": claim_agg["mean"],
                    } if claim_agg["count"] > 0 else None,
                    "claim_to_complete_ms": {
                        "count": int(complete_agg["count"]),
                        "mean_ms": complete_agg["mean"],
                    } if complete_agg["count"] > 0 else None,
                },
            },
            "sample_count": len(self._samples),
        }


# Convenience functions for direct metric recording

def event_to_seen(emitter: MetricsEmitter, event_type: str, elapsed_ms: float) -> None:
    """Record event-to-seen latency."""
    emitter.record("event_to_seen_ms", elapsed_ms, agent_id=emitter.agent_id, event_type=event_type)


def event_to_claim(emitter: MetricsEmitter, source_type: str, elapsed_ms: float) -> None:
    """Record event-to-claim latency."""
    emitter.record("event_to_claim_ms", elapsed_ms, agent_id=emitter.agent_id, source_type=source_type)


def claim_to_complete(emitter: MetricsEmitter, source_type: str, elapsed_ms: float) -> None:
    """Record claim-to-complete latency."""
    emitter.record("claim_to_complete_ms", elapsed_ms, agent_id=emitter.agent_id, source_type=source_type)


def update_pending_inbox(emitter: MetricsEmitter, count: int) -> None:
    """Update pending inbox count."""
    emitter.record("pending_inbox", float(count), agent_id=emitter.agent_id)


def update_unacked_mentions(emitter: MetricsEmitter, count: int) -> None:
    """Update unacked mention count."""
    emitter.record("unacked_mentions", float(count), agent_id=emitter.agent_id)


def increment_timeout_recovery(emitter: MetricsEmitter) -> None:
    """Increment timeout recovery counter."""
    emitter.increment("timeout_recoveries", agent_id=emitter.agent_id)
