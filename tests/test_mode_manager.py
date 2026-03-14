from canopykit import AgentMode, CoordinationSnapshot
from canopykit.mode_manager import DefaultModeManager, FeedSourceState


def make_snapshot(
    *,
    blind_window_seconds=10,
    pending_inbox=0,
    unacked_mentions=0,
):
    return CoordinationSnapshot(
        wake_source="events",
        canopy_poll_interval_seconds=15,
        blind_window_seconds=blind_window_seconds,
        pending_inbox=pending_inbox,
        unacked_mentions=unacked_mentions,
        last_event_cursor_seen=10,
        mode=AgentMode.BACKGROUND,
    )


def test_relay_grade_requires_agent_scoped_feed_and_healthy_metrics():
    manager = DefaultModeManager()
    snapshot = make_snapshot()
    feed_state = FeedSourceState(
        endpoint="/api/v1/agents/me/events",
        status_code=200,
        error_class="",
        active_feed_source="agent_scoped",
        fallback_reason="",
    )
    health_report = {"health": "healthy", "mode": "relay"}

    decision = manager.decide(snapshot, health_report=health_report, feed_state=feed_state)

    assert decision.mode == AgentMode.RELAY_GRADE
    assert decision.eligible_for_relay is True
    assert decision.compatibility_mode is False


def test_global_feed_forces_support_not_relay():
    manager = DefaultModeManager()
    snapshot = make_snapshot()
    feed_state = FeedSourceState(
        endpoint="/api/v1/events",
        status_code=404,
        error_class="not_found",
        active_feed_source="global",
        fallback_reason="404_on_preferred",
    )
    health_report = {"health": "healthy", "mode": "relay"}

    decision = manager.decide(snapshot, health_report=health_report, feed_state=feed_state)

    assert decision.mode == AgentMode.SUPPORT
    assert decision.eligible_for_relay is False
    assert decision.compatibility_mode is True
    assert "compatibility:global" in decision.reasons


def test_high_backlog_degrades_to_background():
    manager = DefaultModeManager()
    snapshot = make_snapshot(pending_inbox=120, unacked_mentions=50)
    health_report = {"health": "unhealthy", "mode": "support"}

    decision = manager.decide(snapshot, health_report=health_report)

    assert decision.mode == AgentMode.BACKGROUND
    assert decision.eligible_for_relay is False


def test_blocked_too_long_forces_background():
    manager = DefaultModeManager()
    snapshot = make_snapshot()
    health_report = {"health": "healthy", "mode": "relay"}

    decision = manager.decide(
        snapshot,
        health_report=health_report,
        blocked_duration_seconds=240,
    )

    assert decision.mode == AgentMode.BACKGROUND
    assert "blocked_too_long:240s" in decision.reasons


def test_support_mode_for_moderate_blind_window():
    manager = DefaultModeManager()
    snapshot = make_snapshot(blind_window_seconds=120, pending_inbox=3, unacked_mentions=2)
    health_report = {"health": "degraded", "mode": "support"}

    decision = manager.decide(snapshot, health_report=health_report)

    assert decision.mode == AgentMode.SUPPORT
    assert decision.eligible_for_relay is False
