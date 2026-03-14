from __future__ import annotations

import json
from pathlib import Path

import pytest

from canopykit.__main__ import main as cli_main
from canopykit.config import CanopyKitConfig
from canopykit.mode_manager import ModeDecision
from canopykit.runloop import CanopyRunLoop, RunLoopConfig, build_run_config
from canopykit.runtime import AgentMode, CoordinationSnapshot


class _FakeProbe:
    endpoint = "/api/v1/agents/me/events"
    status_code = 200
    error_class = ""
    fallback_reason = ""


class _FakeAdapter:
    def __init__(self, polls: list[tuple[list[dict[str, object]], int | None]]):
        self._polls = list(polls)
        self.cursor = 0
        self.feed_source = type("FeedSource", (), {"value": "agent_scoped"})()
        self.last_probe_result = _FakeProbe()
        self.current_backoff = None

    def poll(self, types=None):
        items, next_seq = self._polls.pop(0)
        if next_seq is not None:
            self.cursor = next_seq
        return items, next_seq

    def should_heartbeat_fallback(self):
        return False

    def close(self):
        return None


class _FakeInboxSupervisor:
    def __init__(self, snapshot: CoordinationSnapshot, item_sets: list[list[dict[str, object]]]):
        self._snapshot = snapshot
        self._item_sets = [list(items) for items in item_sets]
        self.mark_seen_ids: list[str] = []

    def snapshot(self):
        return self._snapshot

    def actionable_items(self, limit=5):
        items = self._item_sets.pop(0)
        return items[:limit]

    def mark_seen(self, inbox_id: str):
        self.mark_seen_ids.append(inbox_id)
        from canopykit.inbox_supervisor import InboxPatchResult

        return InboxPatchResult(applied=True, status_code=200)


class _FakeMetrics:
    def __init__(self):
        self.agent_id = "agent-1"
        self.values: dict[str, float] = {}

    def record(self, metric, value, **labels):
        self.values[metric] = value

    def health_report(self):
        return {"health": "healthy", "mode": "support"}


class _FakeModeManager:
    def decide(self, snapshot, *, health_report=None, feed_state=None, blocked_duration_seconds=None):
        return ModeDecision(
            mode=AgentMode.SUPPORT,
            eligible_for_relay=False,
            compatibility_mode=False,
            reasons=("support_ready",),
        )

    def classify(self, snapshot):
        return AgentMode.SUPPORT


def test_run_cycle_writes_status_and_actions_for_inbox_and_channel_work(tmp_path: Path):
    config = RunLoopConfig(
        base_url="http://localhost:7770",
        api_key="secret",
        agent_id="pilot-agent",
        data_dir=str(tmp_path / "runtime"),
        inbox_limit=5,
        watched_channel_ids=("Cagent",),
        agent_handles=("Pilot_Agent",),
        mark_seen=True,
    )
    adapter = _FakeAdapter(
        [
            (
                [
                    {
                        "event_type": "channel.message.created",
                        "channel_id": "Cagent",
                        "message_id": "M1",
                    }
                ],
                12,
            )
        ]
    )
    snapshot = CoordinationSnapshot(
        wake_source="inbox",
        canopy_poll_interval_seconds=15,
        blind_window_seconds=15,
        pending_inbox=1,
        unacked_mentions=2,
        last_event_cursor_seen=12,
        mode=AgentMode.SUPPORT,
    )
    supervisor = _FakeInboxSupervisor(
        snapshot,
        [
            [
                {
                    "id": "INB1",
                    "status": "pending",
                    "trigger_type": "mention",
                    "source_type": "channel_message",
                    "source_id": "M1",
                    "payload": {"channel_id": "Cagent"},
                }
            ]
        ],
    )
    loop = CanopyRunLoop(
        config,
        event_adapter=adapter,
        inbox_supervisor=supervisor,
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
        message_resolver=lambda channel_id, message_id: {
            "id": message_id,
            "channel_id": channel_id,
            "user_id": "user_human",
            "content": "@Pilot_Agent please take this next step",
        },
    )

    status = loop.run_cycle()
    loop.close()

    assert supervisor.mark_seen_ids == ["INB1"]
    assert status["feed_probe"]["feed_source"] == "agent_scoped"
    assert status["channel_routing"]["actionable"] == 1
    assert status["queue"]["actionable_count"] == 2
    assert status["queue"]["by_kind"] == {"channel": 1, "inbox": 1}

    status_path = Path(config.data_dir) / "run-status.json"
    actions_path = Path(config.data_dir) / "actions.jsonl"
    assert status_path.exists()
    assert actions_path.exists()

    written = json.loads(status_path.read_text())
    assert written["queue"]["actionable_count"] == 2

    action_rows = [json.loads(line) for line in actions_path.read_text().splitlines()]
    assert [row["kind"] for row in action_rows] == ["channel_task", "inbox_item"]


def test_runloop_does_not_reconcile_truncated_inbox_views(tmp_path: Path):
    data_dir = str(tmp_path / "runtime")

    first_loop = CanopyRunLoop(
        RunLoopConfig(
            base_url="http://localhost:7770",
            api_key="secret",
            agent_id="agent-alpha",
            data_dir=data_dir,
            inbox_limit=10,
        ),
        event_adapter=_FakeAdapter([([], None)]),
        inbox_supervisor=_FakeInboxSupervisor(
            CoordinationSnapshot(
                wake_source="inbox",
                canopy_poll_interval_seconds=15,
                blind_window_seconds=15,
                pending_inbox=2,
                unacked_mentions=0,
                last_event_cursor_seen=5,
                mode=AgentMode.SUPPORT,
            ),
            [
                [
                    {"id": "INB1", "status": "pending", "source_id": "M1"},
                    {"id": "INB2", "status": "pending", "source_id": "M2"},
                ]
            ],
        ),
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )
    first_loop.run_cycle()
    first_loop.close()

    second_loop = CanopyRunLoop(
        RunLoopConfig(
            base_url="http://localhost:7770",
            api_key="secret",
            agent_id="agent-alpha",
            data_dir=data_dir,
            inbox_limit=1,
        ),
        event_adapter=_FakeAdapter([([], None)]),
        inbox_supervisor=_FakeInboxSupervisor(
            CoordinationSnapshot(
                wake_source="inbox",
                canopy_poll_interval_seconds=15,
                blind_window_seconds=15,
                pending_inbox=2,
                unacked_mentions=0,
                last_event_cursor_seen=6,
                mode=AgentMode.SUPPORT,
            ),
            [[{"id": "INB1", "status": "pending", "source_id": "M1"}]],
        ),
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )

    status = second_loop.run_cycle()
    second_loop.close()

    assert status["queue"]["actionable_count"] == 2
    assert status["queue"]["by_kind"] == {"inbox": 2}
    assert status["queue"]["by_status"] == {"pending": 2}


def test_seen_items_do_not_trigger_blocked_too_long_mode_reason(tmp_path: Path):
    config = RunLoopConfig(
        base_url="http://localhost:7770",
        api_key="secret",
        agent_id="pilot-agent",
        data_dir=str(tmp_path / "runtime"),
        inbox_limit=5,
    )
    loop = CanopyRunLoop(
        config,
        event_adapter=_FakeAdapter([([], None)]),
        inbox_supervisor=_FakeInboxSupervisor(
            CoordinationSnapshot(
                wake_source="inbox",
                canopy_poll_interval_seconds=15,
                blind_window_seconds=15,
                pending_inbox=1,
                unacked_mentions=0,
                last_event_cursor_seen=12,
                mode=AgentMode.SUPPORT,
            ),
            [[{"id": "INB1", "status": "seen", "source_id": "M1"}]],
        ),
        metrics=_FakeMetrics(),
    )

    status = loop.run_cycle()
    loop.close()

    assert "blocked_too_long" not in " ".join(status["mode_decision"]["reasons"])
    assert status["queue"]["by_status"] == {"seen": 1}


def test_runloop_continues_when_mark_seen_is_rate_limited(tmp_path: Path):
    from canopykit.inbox_supervisor import InboxPatchResult

    class _RateLimitedInboxSupervisor(_FakeInboxSupervisor):
        def mark_seen(self, inbox_id: str):
            self.mark_seen_ids.append(inbox_id)
            return InboxPatchResult(
                applied=False,
                retryable=True,
                status_code=429,
                error_class="HTTPError",
            )

    config = RunLoopConfig(
        base_url="http://localhost:7770",
        api_key="secret",
        agent_id="pilot-agent",
        data_dir=str(tmp_path / "runtime"),
        inbox_limit=5,
        mark_seen=True,
    )
    loop = CanopyRunLoop(
        config,
        event_adapter=_FakeAdapter([([], None)]),
        inbox_supervisor=_RateLimitedInboxSupervisor(
            CoordinationSnapshot(
                wake_source="inbox",
                canopy_poll_interval_seconds=15,
                blind_window_seconds=15,
                pending_inbox=1,
                unacked_mentions=0,
                last_event_cursor_seen=12,
                mode=AgentMode.SUPPORT,
            ),
            [[{"id": "INB1", "status": "pending", "source_id": "M1"}]],
        ),
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )

    status = loop.run_cycle()
    loop.close()

    assert status["mark_seen"]["enabled"] is True
    assert status["mark_seen"]["failures"] == [
        {
            "inbox_id": "INB1",
            "status_code": 429,
            "retryable": True,
            "error_class": "HTTPError",
        }
    ]
    assert status["queue"]["by_status"] == {"pending": 1}


def test_build_run_config_uses_file_key_and_config_defaults(tmp_path: Path):
    api_key_file = tmp_path / "agent.key"
    api_key_file.write_text("file-secret\n")
    cfg = CanopyKitConfig(
        base_url="http://canopy.local:7770",
        api_key="config-secret",
        watched_channel_ids=("Cagent",),
        agent_handles=("Pilot_Agent",),
        agent_user_ids=("user_agent_self",),
        require_direct_address=False,
        inbox_limit=77,
        event_poll_interval_seconds=22,
        heartbeat_fallback_seconds=90,
    )

    run_cfg = build_run_config(
        base_url="",
        api_key="",
        api_key_file=str(api_key_file),
        config=cfg,
        agent_id="pilot-agent",
        data_dir=str(tmp_path / "runtime"),
        poll_interval_seconds=0,
        heartbeat_fallback_seconds=0,
        request_timeout_seconds=9.5,
        event_limit=40,
        inbox_limit=0,
        mark_seen=True,
        status_path="",
        actions_path="",
    )

    assert run_cfg.api_key == "file-secret"
    assert run_cfg.base_url == "http://canopy.local:7770"
    assert run_cfg.watched_channel_ids == ("Cagent",)
    assert run_cfg.agent_handles == ("Pilot_Agent",)
    assert run_cfg.agent_user_ids == ("user_agent_self",)
    assert run_cfg.require_direct_address is False
    assert run_cfg.inbox_limit == 77
    assert run_cfg.poll_interval_seconds == 22
    assert run_cfg.heartbeat_fallback_seconds == 90
    assert run_cfg.mark_seen is True


def test_run_cli_executes_loop_and_prints_result(monkeypatch, capsys, tmp_path: Path):
    created = {}

    class _FakeRunLoop:
        def __init__(self, config):
            created["config"] = config
            self.closed = False

        def run(self, *, max_cycles=None, duration_seconds=None):
            created["max_cycles"] = max_cycles
            created["duration_seconds"] = duration_seconds
            return {"status": "ok", "agent_id": created["config"].agent_id}

        def close(self):
            self.closed = True
            created["closed"] = True

    monkeypatch.setattr("canopykit.__main__.CanopyRunLoop", _FakeRunLoop)

    rc = cli_main(
        [
            "run",
            "--base-url",
            "http://localhost:7770",
            "--api-key",
            "secret",
            "--agent-id",
            "pilot-agent",
            "--data-dir",
            str(tmp_path / "runtime"),
            "--mark-seen",
            "--max-cycles",
            "1",
        ]
    )

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["status"] == "ok"
    assert created["config"].mark_seen is True
    assert created["max_cycles"] == 1
    assert created["duration_seconds"] is None
    assert created["closed"] is True


def _make_snapshot(pending_inbox: int = 0) -> CoordinationSnapshot:
    return CoordinationSnapshot(
        wake_source="heartbeat",
        canopy_poll_interval_seconds=15,
        blind_window_seconds=15,
        pending_inbox=pending_inbox,
        unacked_mentions=0,
        last_event_cursor_seen=1,
        mode=AgentMode.SUPPORT,
    )


def test_status_includes_snapshot_age_and_consecutive_failures_zero_on_success(
    tmp_path: Path,
) -> None:
    """On a successful cycle the status carries snapshot_age_seconds and
    consecutive_snapshot_failures == 0 in heartbeat_snapshot."""
    config = RunLoopConfig(
        base_url="http://localhost:7770",
        api_key="secret",
        agent_id="goose",
        data_dir=str(tmp_path / "runtime"),
    )
    loop = CanopyRunLoop(
        config,
        event_adapter=_FakeAdapter([([], None)]),
        inbox_supervisor=_FakeInboxSupervisor(_make_snapshot(), [[]]),
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )
    status = loop.run_cycle()
    loop.close()

    hs = status["heartbeat_snapshot"]
    assert "snapshot_age_seconds" in hs
    assert hs["snapshot_age_seconds"] >= 0
    assert hs["consecutive_snapshot_failures"] == 0


def test_consecutive_snapshot_failures_increments_on_error(tmp_path: Path) -> None:
    """Each cycle where snapshot() raises must increment consecutive_snapshot_failures."""

    class _FailingInboxSupervisor:
        call_count = 0

        def snapshot(self):
            self.call_count += 1
            raise RuntimeError("canopy unreachable")

        def actionable_items(self, limit=5):
            return []

    config = RunLoopConfig(
        base_url="http://localhost:7770",
        api_key="secret",
        agent_id="goose",
        data_dir=str(tmp_path / "runtime"),
        poll_interval_seconds=1,
        heartbeat_fallback_seconds=1,
    )
    sup = _FailingInboxSupervisor()
    loop = CanopyRunLoop(
        config,
        event_adapter=_FakeAdapter([([], None), ([], None)]),
        inbox_supervisor=sup,
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )

    with pytest.raises(RuntimeError):
        loop.run_cycle()

    assert loop._consecutive_snapshot_failures == 1

    with pytest.raises(RuntimeError):
        loop.run_cycle()

    assert loop._consecutive_snapshot_failures == 2
    loop.close()


def test_consecutive_snapshot_failures_resets_on_recovery(tmp_path: Path) -> None:
    """After two failing cycles, a successful snapshot resets the counter to 0."""

    class _EventuallyRecoveringInboxSupervisor:
        def __init__(self, fail_times: int, snap: CoordinationSnapshot) -> None:
            self._fail_times = fail_times
            self._snap = snap

        def snapshot(self):
            if self._fail_times > 0:
                self._fail_times -= 1
                raise RuntimeError("transient failure")
            return self._snap

        def actionable_items(self, limit=5):
            return []

    config = RunLoopConfig(
        base_url="http://localhost:7770",
        api_key="secret",
        agent_id="goose",
        data_dir=str(tmp_path / "runtime"),
        poll_interval_seconds=1,
        heartbeat_fallback_seconds=1,
    )
    sup = _EventuallyRecoveringInboxSupervisor(fail_times=2, snap=_make_snapshot())
    loop = CanopyRunLoop(
        config,
        event_adapter=_FakeAdapter([([], None), ([], None), ([], None)]),
        inbox_supervisor=sup,
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )

    # Two failure cycles
    with pytest.raises(RuntimeError):
        loop.run_cycle()
    assert loop._consecutive_snapshot_failures == 1

    with pytest.raises(RuntimeError):
        loop.run_cycle()
    assert loop._consecutive_snapshot_failures == 2

    # Recovery cycle
    status = loop.run_cycle()
    loop.close()

    assert loop._consecutive_snapshot_failures == 0
    assert status["heartbeat_snapshot"]["consecutive_snapshot_failures"] == 0


def test_action_log_bounded_by_max_action_log_lines(tmp_path: Path) -> None:
    """actions.jsonl must not exceed cap + headroom once the lazy-trim threshold
    is crossed.  The lazy trim fires when lines > cap + max(10, cap//10) and
    brings the file back to cap lines."""
    cap = 50
    # headroom = max(10, cap//10) = max(10, 5) = 10; threshold = 60
    # Write 70 items total so the trim fires at least once.
    config = RunLoopConfig(
        base_url="http://localhost:7770",
        api_key="secret",
        agent_id="goose",
        data_dir=str(tmp_path / "runtime"),
        inbox_limit=100,
        max_action_log_lines=cap,
    )

    def _item(idx: int) -> dict:
        return {"id": f"INB{idx}", "status": "pending", "source_id": f"M{idx}"}

    # Cycle 1: 40 new items → 40 lines (below threshold 60)
    # Cycle 2: 30 new items → 70 total, trim fires at item 61 → file trimmed to 50
    batch_a = [_item(i) for i in range(1, 41)]    # 40 items
    batch_b = [_item(i) for i in range(41, 71)]   # 30 items → total 70

    sup1 = _FakeInboxSupervisor(_make_snapshot(pending_inbox=40), [batch_a])
    loop = CanopyRunLoop(
        config,
        event_adapter=_FakeAdapter([([], None)]),
        inbox_supervisor=sup1,
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )
    loop.run_cycle()
    loop.close()

    sup2 = _FakeInboxSupervisor(_make_snapshot(pending_inbox=30), [batch_b])
    loop2 = CanopyRunLoop(
        config,
        event_adapter=_FakeAdapter([([], None)]),
        inbox_supervisor=sup2,
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )
    status = loop2.run_cycle()
    loop2.close()

    max_allowed = cap + max(10, cap // 10)
    actions_path = Path(config.data_dir) / "actions.jsonl"
    lines = actions_path.read_text().splitlines()
    assert len(lines) <= max_allowed, f"Expected ≤{max_allowed} lines, got {len(lines)}"
    assert status["action_log"]["lines"] <= max_allowed
    assert status["action_log"]["cap"] == cap


def test_action_log_status_present_with_zero_when_empty(tmp_path: Path) -> None:
    """action_log section is present even when no events have been appended."""
    config = RunLoopConfig(
        base_url="http://localhost:7770",
        api_key="secret",
        agent_id="goose",
        data_dir=str(tmp_path / "runtime"),
    )
    loop = CanopyRunLoop(
        config,
        event_adapter=_FakeAdapter([([], None)]),
        inbox_supervisor=_FakeInboxSupervisor(_make_snapshot(), [[]]),
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )
    status = loop.run_cycle()
    loop.close()

    assert "action_log" in status
    assert status["action_log"]["lines"] == 0
    assert status["action_log"]["cap"] == config.max_action_log_lines
