"""Continuous daemon-mode coordination loop for CanopyKit/CanopyKit.

The loop is intentionally conservative:
- consume the Canopy event feed continuously
- maintain an operator-visible actionable queue
- route explicitly addressed channel work into that queue
- optionally mark inbox items `seen`

It does not attempt open-world interpretation or auto-complete work. Those
remain higher-layer concerns.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import requests

from .channel_bridge import ChannelBridge, ChannelBridgeConfig
from .channel_router import CHANNEL_EVENT_TYPES, ChannelEventRouter, ChannelRouteOutcome
from .config import CanopyKitConfig
from .event_adapter import AgentEventFeedConfig, EventAdapter, FeedProbeResult, FeedSource
from .inbox_supervisor import ACTIONABLE_STATUSES, CanopyInboxSupervisor, InboxSupervisorConfig
from .metrics import MetricsEmitter, update_pending_inbox, update_unacked_mentions
from .mode_manager import DefaultModeManager, FeedSourceState, ModeDecision
from .redaction import redact_secrets
from .runtime import CoordinationSnapshot


@dataclass(slots=True)
class RunLoopConfig:
    base_url: str
    api_key: str
    agent_id: str
    data_dir: str = "data/canopykit"
    poll_interval_seconds: int = 15
    heartbeat_fallback_seconds: int = 60
    request_timeout_seconds: float = 10.0
    event_limit: int = 50
    inbox_limit: int = 25
    watched_channel_ids: tuple[str, ...] = ()
    agent_handles: tuple[str, ...] = ()
    agent_user_ids: tuple[str, ...] = ()
    require_direct_address: bool = True
    mark_seen: bool = False
    status_path: str = ""
    actions_path: str = ""
    max_action_log_lines: int = 10000


class RuntimeQueueStore:
    """Durable local store for actionable runtime work."""

    def __init__(self, data_dir: str, agent_id: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "runloop.db"
        self.agent_id = agent_id
        self._conn = sqlite3.connect(str(self.db_path))
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_queue (
                work_key TEXT PRIMARY KEY,
                source_kind TEXT NOT NULL,
                source_id TEXT NOT NULL,
                inbox_id TEXT,
                channel_id TEXT,
                message_id TEXT,
                status TEXT NOT NULL,
                actionable INTEGER NOT NULL DEFAULT 1,
                reasons_json TEXT NOT NULL DEFAULT '[]',
                payload_json TEXT NOT NULL DEFAULT '{}',
                first_seen_ms INTEGER NOT NULL,
                last_seen_ms INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_queue_actionable ON work_queue(actionable, source_kind, last_seen_ms)"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def upsert_inbox_item(self, item: Mapping[str, Any], now_ms: int) -> bool:
        inbox_id = str(item.get("id") or "")
        if not inbox_id:
            return False
        work_key = f"inbox:{inbox_id}"
        status = str(item.get("status") or "pending").strip().lower()
        actionable = 1 if status in ACTIONABLE_STATUSES else 0
        payload = {
            "trigger_type": item.get("trigger_type"),
            "source_type": item.get("source_type"),
            "source_id": item.get("source_id"),
            "channel_id": item.get("channel_id") or item.get("payload", {}).get("channel_id"),
            "completion_ref": item.get("completion_ref"),
        }
        existing = self._conn.execute(
            "SELECT first_seen_ms FROM work_queue WHERE work_key = ?",
            (work_key,),
        ).fetchone()
        first_seen_ms = int(existing[0]) if existing else now_ms
        self._conn.execute(
            """
            INSERT OR REPLACE INTO work_queue (
                work_key, source_kind, source_id, inbox_id, channel_id, message_id,
                status, actionable, reasons_json, payload_json, first_seen_ms, last_seen_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                work_key,
                "inbox",
                str(item.get("source_id") or inbox_id),
                inbox_id,
                str(payload.get("channel_id") or ""),
                "",
                status,
                actionable,
                "[]",
                json.dumps(payload, sort_keys=True),
                first_seen_ms,
                now_ms,
            ),
        )
        self._conn.commit()
        return existing is None

    def reconcile_inbox(self, current_ids: Iterable[str], now_ms: int) -> None:
        current = {str(value) for value in current_ids if value}
        rows = self._conn.execute(
            """
            SELECT work_key, inbox_id FROM work_queue
            WHERE source_kind = 'inbox' AND actionable = 1
            """
        ).fetchall()
        for work_key, inbox_id in rows:
            if inbox_id not in current:
                self._conn.execute(
                    """
                    UPDATE work_queue
                    SET actionable = 0, status = 'resolved_elsewhere', last_seen_ms = ?
                    WHERE work_key = ?
                    """,
                    (now_ms, work_key),
                )
        self._conn.commit()

    def upsert_channel_task(self, outcome: ChannelRouteOutcome, now_ms: int) -> bool:
        if not outcome.actionable or outcome.task is None:
            return False
        task = outcome.task
        work_key = f"channel:{task.channel_id}:{task.message_id}"
        payload = {
            "event_type": task.event_type,
            "content": task.content,
            "author_user_id": task.author_user_id,
            "direct_mentions": list(task.routing.direct_mentions),
            "structured_assignments": {
                key: list(value) for key, value in task.routing.structured_assignments.items()
            },
        }
        reasons = list(task.routing.reasons)
        existing = self._conn.execute(
            "SELECT first_seen_ms FROM work_queue WHERE work_key = ?",
            (work_key,),
        ).fetchone()
        first_seen_ms = int(existing[0]) if existing else now_ms
        self._conn.execute(
            """
            INSERT OR REPLACE INTO work_queue (
                work_key, source_kind, source_id, inbox_id, channel_id, message_id,
                status, actionable, reasons_json, payload_json, first_seen_ms, last_seen_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                work_key,
                "channel",
                task.message_id,
                "",
                task.channel_id,
                task.message_id,
                "queued",
                1,
                json.dumps(reasons, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                first_seen_ms,
                now_ms,
            ),
        )
        self._conn.commit()
        return existing is None

    def oldest_actionable_age_seconds(self, now_ms: int) -> Optional[int]:
        row = self._conn.execute(
            "SELECT MIN(first_seen_ms) FROM work_queue WHERE actionable = 1"
        ).fetchone()
        first_seen_ms = row[0] if row else None
        if first_seen_ms is None:
            return None
        return max(0, int((now_ms - int(first_seen_ms)) / 1000))

    def oldest_pending_age_seconds(self, now_ms: int) -> Optional[int]:
        row = self._conn.execute(
            "SELECT MIN(first_seen_ms) FROM work_queue WHERE actionable = 1 AND status = 'pending'"
        ).fetchone()
        first_seen_ms = row[0] if row else None
        if first_seen_ms is None:
            return None
        return max(0, int((now_ms - int(first_seen_ms)) / 1000))

    def summary(self, limit: int = 10) -> Dict[str, Any]:
        total_actionable = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM work_queue WHERE actionable = 1"
            ).fetchone()[0]
        )
        by_kind = {
            row[0]: int(row[1])
            for row in self._conn.execute(
                """
                SELECT source_kind, COUNT(*)
                FROM work_queue
                WHERE actionable = 1
                GROUP BY source_kind
                """
            ).fetchall()
        }
        by_status = {
            row[0]: int(row[1])
            for row in self._conn.execute(
                """
                SELECT status, COUNT(*)
                FROM work_queue
                WHERE actionable = 1
                GROUP BY status
                """
            ).fetchall()
        }
        rows = self._conn.execute(
            """
            SELECT work_key, source_kind, source_id, inbox_id, channel_id, message_id,
                   status, reasons_json, payload_json, first_seen_ms, last_seen_ms
            FROM work_queue
            WHERE actionable = 1
            ORDER BY last_seen_ms DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        recent = []
        for row in rows:
            recent.append(
                {
                    "work_key": row[0],
                    "source_kind": row[1],
                    "source_id": row[2],
                    "inbox_id": row[3],
                    "channel_id": row[4],
                    "message_id": row[5],
                    "status": row[6],
                    "reasons": json.loads(row[7] or "[]"),
                    "payload": json.loads(row[8] or "{}"),
                    "first_seen_ms": row[9],
                    "last_seen_ms": row[10],
                }
            )
        return {
            "actionable_count": total_actionable,
            "by_kind": by_kind,
            "by_status": by_status,
            "recent_items": recent,
        }


class CanopyRunLoop:
    """Continuous daemon-mode coordination loop."""

    def __init__(
        self,
        config: RunLoopConfig,
        *,
        event_adapter: Optional[EventAdapter] = None,
        inbox_supervisor: Optional[CanopyInboxSupervisor] = None,
        metrics: Optional[MetricsEmitter] = None,
        mode_manager: Optional[DefaultModeManager] = None,
        message_resolver: Optional[callable] = None,
    ) -> None:
        self.config = config
        self._event_adapter = event_adapter or EventAdapter(
            AgentEventFeedConfig(
                base_url=config.base_url,
                api_key=config.api_key,
                agent_id=config.agent_id,
                limit=config.event_limit,
                poll_interval_seconds=config.poll_interval_seconds,
                heartbeat_fallback_seconds=config.heartbeat_fallback_seconds,
                request_timeout_seconds=config.request_timeout_seconds,
                data_dir=config.data_dir,
            )
        )
        self._inbox_supervisor = inbox_supervisor or CanopyInboxSupervisor(
            InboxSupervisorConfig(
                base_url=config.base_url,
                api_key=config.api_key,
                request_timeout_seconds=config.request_timeout_seconds,
                inbox_limit=max(1, config.inbox_limit),
            )
        )
        self._metrics = metrics or MetricsEmitter(
            agent_id=config.agent_id,
            db_path=Path(config.data_dir) / "metrics.db",
        )
        self._mode_manager = mode_manager or DefaultModeManager()
        self._store = RuntimeQueueStore(config.data_dir, config.agent_id)
        self._channel_router = ChannelEventRouter(
            ChannelBridge(
                ChannelBridgeConfig.from_iterables(
                    agent_handles=config.agent_handles,
                    watched_channel_ids=config.watched_channel_ids,
                    agent_user_ids=config.agent_user_ids,
                    require_direct_address=config.require_direct_address,
                )
            )
        )
        self._message_resolver = message_resolver or self._resolve_channel_message
        self._status_path = Path(config.status_path) if config.status_path else Path(config.data_dir) / "run-status.json"
        self._actions_path = Path(config.actions_path) if config.actions_path else Path(config.data_dir) / "actions.jsonl"
        self._status_path.parent.mkdir(parents=True, exist_ok=True)
        self._actions_path.parent.mkdir(parents=True, exist_ok=True)
        self._cycle = 0
        self._last_snapshot: Optional[CoordinationSnapshot] = None
        self._last_snapshot_ms: int = 0
        self._consecutive_snapshot_failures: int = 0
        self._action_log_lines: int = self._count_file_lines(self._actions_path)

    def close(self) -> None:
        self._event_adapter.close()
        self._store.close()

    def run_cycle(self) -> Dict[str, Any]:
        now_ms = int(time.time() * 1000)
        self._cycle += 1
        self._mark_seen_failures: List[Dict[str, Any]] = []

        channel_event_types = tuple(CHANNEL_EVENT_TYPES) if self.config.watched_channel_ids else ()
        selected_types = tuple(dict.fromkeys((*EventAdapter.DEFAULT_EVENT_TYPES, *channel_event_types)))

        items, _ = self._event_adapter.poll(types=selected_types)
        routed_outcomes = self._route_channel_events(items, now_ms)

        snapshot = self._snapshot_if_needed(items, now_ms)
        if snapshot is None:
            snapshot = self._last_snapshot or CoordinationSnapshot(
                wake_source="events",
                canopy_poll_interval_seconds=self.config.poll_interval_seconds,
                blind_window_seconds=self.config.poll_interval_seconds,
                pending_inbox=0,
                unacked_mentions=0,
                last_event_cursor_seen=self._event_adapter.cursor,
                mode=self._mode_manager.classify(
                    CoordinationSnapshot(
                        wake_source="events",
                        canopy_poll_interval_seconds=self.config.poll_interval_seconds,
                        blind_window_seconds=self.config.poll_interval_seconds,
                        pending_inbox=0,
                        unacked_mentions=0,
                        last_event_cursor_seen=self._event_adapter.cursor,
                        mode=None,  # type: ignore[arg-type]
                    )
                ),
            )

        health_report = self._metrics.health_report()
        probe = self._event_adapter.last_probe_result
        feed_state = FeedSourceState(
            endpoint=probe.endpoint if probe else "",
            status_code=probe.status_code if probe else 0,
            error_class=probe.error_class if probe else "",
            active_feed_source=self._event_adapter.feed_source.value,
            fallback_reason=probe.fallback_reason if probe else "",
        )
        blocked_duration = self._store.oldest_pending_age_seconds(now_ms)
        mode_decision = self._mode_manager.decide(
            snapshot,
            health_report=health_report,
            feed_state=feed_state,
            blocked_duration_seconds=blocked_duration,
        )

        status = {
            "timestamp_ms": now_ms,
            "cycle": self._cycle,
            "agent_id": self.config.agent_id,
            "product_name": "CanopyKit",
            "feed_probe": {
                "feed_source": self._event_adapter.feed_source.value,
                "endpoint": probe.endpoint if probe else "",
                "status_code": probe.status_code if probe else 0,
                "error_class": probe.error_class if probe else "",
                "fallback_reason": probe.fallback_reason if probe else "",
            },
            "event_feed": {
                "selected_types": list(selected_types),
                "cursor": self._event_adapter.cursor,
                "items_seen_this_cycle": len(items),
                "backoff_active": self._event_adapter.current_backoff is not None,
                "heartbeat_fallback_due": self._event_adapter.should_heartbeat_fallback(),
            },
            "heartbeat_snapshot": {
                "wake_source": snapshot.wake_source,
                "poll_interval_seconds": snapshot.canopy_poll_interval_seconds,
                "blind_window_seconds": snapshot.blind_window_seconds,
                "pending_inbox": snapshot.pending_inbox,
                "unacked_mentions": snapshot.unacked_mentions,
                "last_event_cursor_seen": snapshot.last_event_cursor_seen,
                "snapshot_age_seconds": max(0, int((now_ms - self._last_snapshot_ms) / 1000)),
                "consecutive_snapshot_failures": self._consecutive_snapshot_failures,
            },
            "mode_decision": {
                "mode": mode_decision.mode.value,
                "eligible_for_relay": mode_decision.eligible_for_relay,
                "compatibility_mode": mode_decision.compatibility_mode,
                "reasons": list(mode_decision.reasons),
            },
            "channel_routing": self._summarize_routing(routed_outcomes),
            "queue": self._store.summary(),
            "health_report": health_report,
            "mark_seen": {
                "enabled": self.config.mark_seen,
                "failures": list(self._mark_seen_failures),
            },
            "action_log": {
                "lines": self._action_log_line_count(),
                "cap": self.config.max_action_log_lines,
            },
        }
        self._write_status(status)
        return status

    def run(
        self,
        *,
        max_cycles: Optional[int] = None,
        duration_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        start = time.time()
        last_status: Dict[str, Any] = {}
        try:
            while True:
                if max_cycles is not None and self._cycle >= max_cycles:
                    break
                if duration_seconds is not None and (time.time() - start) >= duration_seconds:
                    break
                last_status = self.run_cycle()
        except KeyboardInterrupt:
            pass
        return last_status

    def _heartbeat_every_cycles(self) -> int:
        interval = max(1, self.config.poll_interval_seconds)
        return max(1, int(math.ceil(self.config.heartbeat_fallback_seconds / interval)))

    def _snapshot_if_needed(
        self,
        items: List[Dict[str, Any]],
        now_ms: int,
    ) -> Optional[CoordinationSnapshot]:
        heartbeat_due = (
            self._cycle == 1
            or bool(items)
            or self._event_adapter.should_heartbeat_fallback()
            or (self._cycle % self._heartbeat_every_cycles() == 0)
        )
        if not heartbeat_due:
            return self._last_snapshot

        try:
            snapshot = self._inbox_supervisor.snapshot()
        except Exception:
            self._consecutive_snapshot_failures += 1
            raise

        actionable_items = self._inbox_supervisor.actionable_items(limit=self.config.inbox_limit)

        current_ids: list[str] = []
        for item in actionable_items:
            inbox_id = str(item.get("id") or "")
            if not inbox_id:
                continue
            current_ids.append(inbox_id)
            if self.config.mark_seen and str(item.get("status") or "").strip().lower() == "pending":
                mark_seen_result = self._inbox_supervisor.mark_seen(inbox_id)
                if mark_seen_result.applied:
                    item = dict(item)
                    item["status"] = "seen"
                else:
                    self._mark_seen_failures.append(
                        {
                            "inbox_id": inbox_id,
                            "status_code": mark_seen_result.status_code,
                            "retryable": mark_seen_result.retryable,
                            "error_class": mark_seen_result.error_class,
                        }
                    )
                    self._append_action_event(
                        {
                            "kind": "mark_seen_failed",
                            "inbox_id": inbox_id,
                            "status_code": mark_seen_result.status_code,
                            "retryable": mark_seen_result.retryable,
                            "error_class": mark_seen_result.error_class,
                            "timestamp_ms": now_ms,
                        }
                    )
            created = self._store.upsert_inbox_item(item, now_ms)
            if created:
                self._append_action_event(
                    {
                        "kind": "inbox_item",
                        "inbox_id": inbox_id,
                        "source_id": item.get("source_id"),
                        "status": item.get("status"),
                        "trigger_type": item.get("trigger_type"),
                        "timestamp_ms": now_ms,
                    }
                )

        # Only reconcile when the actionable inbox view is complete. If the
        # fetched list hit the configured limit, the server may still have more
        # actionable rows that we did not inspect this cycle.
        actionable_complete = len(actionable_items) < self.config.inbox_limit
        if actionable_complete:
            self._store.reconcile_inbox(current_ids, now_ms)
        update_pending_inbox(self._metrics, snapshot.pending_inbox)
        update_unacked_mentions(self._metrics, snapshot.unacked_mentions)

        self._consecutive_snapshot_failures = 0
        self._last_snapshot = snapshot
        self._last_snapshot_ms = now_ms
        return snapshot

    def _route_channel_events(
        self,
        items: Iterable[Mapping[str, Any]],
        now_ms: int,
    ) -> List[ChannelRouteOutcome]:
        outcomes: List[ChannelRouteOutcome] = []
        for item in items:
            event_type = str(item.get("event_type") or "")
            if event_type not in CHANNEL_EVENT_TYPES:
                continue
            outcome = self._channel_router.route_event(item, self._message_resolver)
            outcomes.append(outcome)
            if outcome.actionable:
                created = self._store.upsert_channel_task(outcome, now_ms)
                if created and outcome.task is not None:
                    self._append_action_event(
                        {
                            "kind": "channel_task",
                            "channel_id": outcome.task.channel_id,
                            "message_id": outcome.task.message_id,
                            "routing_reasons": list(outcome.task.routing.reasons),
                            "timestamp_ms": now_ms,
                        }
                    )
        return outcomes

    def _resolve_channel_message(self, channel_id: str, message_id: str) -> Optional[Mapping[str, Any]]:
        response = requests.get(
            f"{self.config.base_url}/api/v1/channels/{channel_id}/messages",
            headers={"X-API-Key": self.config.api_key},
            params={"limit": 100},
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        messages = response.json().get("messages") or []
        for message in messages:
            if str(message.get("id") or "") == message_id:
                return message
        return None

    def _append_action_event(self, payload: Mapping[str, Any]) -> None:
        with open(self._actions_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), sort_keys=True) + "\n")
        self._action_log_lines += 1
        cap = self.config.max_action_log_lines
        # Trim lazily: only rewrite the file when the count exceeds the cap by a
        # 10% headroom (minimum 10 lines), to avoid a rewrite on every append
        # near the boundary.
        if cap > 0 and self._action_log_lines > cap + max(10, cap // 10):
            self._trim_action_log(cap)

    def _trim_action_log(self, cap: int) -> None:
        try:
            with open(self._actions_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
            if len(lines) > cap:
                with open(self._actions_path, "w", encoding="utf-8") as handle:
                    handle.writelines(lines[-cap:])
                self._action_log_lines = cap
            else:
                self._action_log_lines = len(lines)
        except OSError:
            pass

    def _action_log_line_count(self) -> int:
        return self._action_log_lines

    @staticmethod
    def _count_file_lines(path: Path) -> int:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return sum(1 for _ in handle)
        except OSError:
            return 0

    def _write_status(self, status: Mapping[str, Any]) -> None:
        with open(self._status_path, "w", encoding="utf-8") as handle:
            json.dump(redact_secrets(dict(status)), handle, indent=2, sort_keys=True)

    def _summarize_routing(self, outcomes: Iterable[ChannelRouteOutcome]) -> Dict[str, Any]:
        outcomes = list(outcomes)
        if not outcomes:
            return {
                "enabled": bool(self.config.watched_channel_ids),
                "evaluated": 0,
                "actionable": 0,
                "non_actionable": 0,
                "reasons": {},
            }
        reasons: Dict[str, int] = {}
        actionable = 0
        for outcome in outcomes:
            reasons[outcome.reason] = reasons.get(outcome.reason, 0) + 1
            if outcome.actionable:
                actionable += 1
        return {
            "enabled": True,
            "evaluated": len(outcomes),
            "actionable": actionable,
            "non_actionable": len(outcomes) - actionable,
            "reasons": reasons,
        }


def build_run_config(
    *,
    base_url: str,
    api_key: str,
    api_key_file: str,
    config: Optional[CanopyKitConfig],
    agent_id: str,
    data_dir: str,
    poll_interval_seconds: int,
    heartbeat_fallback_seconds: int,
    request_timeout_seconds: float,
    event_limit: int,
    inbox_limit: int,
    mark_seen: bool,
    status_path: str,
    actions_path: str,
) -> RunLoopConfig:
    effective = config or CanopyKitConfig()
    resolved_api_key = (
        api_key
        or _read_api_key(api_key_file)
        or effective.api_key
        or ""
    ).strip()
    if not resolved_api_key:
        raise ValueError("API key required; pass --api-key, --api-key-file, or config.api_key")

    return RunLoopConfig(
        base_url=base_url or effective.base_url,
        api_key=resolved_api_key,
        agent_id=agent_id,
        data_dir=data_dir,
        poll_interval_seconds=max(0, poll_interval_seconds or effective.event_poll_interval_seconds),
        heartbeat_fallback_seconds=max(
            1,
            heartbeat_fallback_seconds or effective.heartbeat_fallback_seconds,
        ),
        request_timeout_seconds=max(0.1, request_timeout_seconds),
        event_limit=max(1, event_limit),
        inbox_limit=max(1, inbox_limit or effective.inbox_limit),
        watched_channel_ids=tuple(effective.watched_channel_ids),
        agent_handles=tuple(effective.agent_handles),
        agent_user_ids=tuple(effective.agent_user_ids),
        require_direct_address=bool(effective.require_direct_address),
        mark_seen=bool(mark_seen),
        status_path=status_path,
        actions_path=actions_path,
    )


def _read_api_key(path: str) -> str:
    if not path:
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


__all__ = [
    "CanopyRunLoop",
    "RunLoopConfig",
    "RuntimeQueueStore",
    "build_run_config",
]
