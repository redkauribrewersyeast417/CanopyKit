from canopykit.runtime import AgentMode, CoordinationSnapshot
from canopykit.config import CanopyKitConfig
from canopykit.__main__ import main as cli_main
from canopykit.shadow_selftest import ShadowSelfTestConfig, ShadowSelfTestRunner, build_shadow_config
from canopykit.mode_manager import ModeDecision


class _FakeProbe:
    endpoint = "/api/v1/agents/me/events"
    status_code = 200
    error_class = ""
    fallback_reason = ""


class _FakeAdapter:
    def __init__(self):
        self.cursor = 10
        self.feed_source = type("FeedSource", (), {"value": "agent_scoped"})()
        self.last_probe_result = _FakeProbe()
        self.current_backoff = None
        self._polls = [
            ([{"event_type": "mention.created"}], 12),
            ([], None),
            ([{"event_type": "inbox.item.created"}], 15),
        ]

    def probe_feed_source(self):
        return self.feed_source

    def poll(self, types=None):
        items, next_seq = self._polls.pop(0)
        if next_seq is not None:
            self.cursor = next_seq
        return items, next_seq

    def should_heartbeat_fallback(self):
        return False

    def fetch_heartbeat(self):
        return {
            "needs_action": True,
            "pending_inbox": 2,
            "unacked_mentions": 1,
            "workspace_event_seq": 15,
            "event_subscription_source": "default",
            "event_subscription_count": 8,
            "event_subscription_types": ["mention.created"],
            "event_subscription_unavailable_types": [],
        }

    def close(self):
        return None


class _FakeInboxSupervisor:
    def snapshot(self):
        return CoordinationSnapshot(
            wake_source="inbox",
            canopy_poll_interval_seconds=5,
            blind_window_seconds=5,
            pending_inbox=2,
            unacked_mentions=1,
            last_event_cursor_seen=15,
            mode=AgentMode.SUPPORT,
        )

    def actionable_items(self, limit=5):
        return [
            {
                "id": "INB1",
                "status": "pending",
                "trigger_type": "mention",
                "source_type": "channel_message",
                "source_id": "M1",
            }
        ]


class _FakeMetrics:
    def __init__(self):
        self.agent_id = "agent-1"
        self.values = {}

    def record(self, metric, value, **labels):
        self.values[metric] = value

    def health_report(self):
        return {"health": "healthy", "mode": "support"}


class _FakeModeManager:
    def decide(self, snapshot, *, health_report=None, feed_state=None):
        return ModeDecision(
            mode=AgentMode.SUPPORT,
            eligible_for_relay=False,
            compatibility_mode=False,
            reasons=("support_ready",),
        )


class _CompatibilityAdapter(_FakeAdapter):
    def __init__(self):
        super().__init__()
        self.feed_source = type("FeedSource", (), {"value": "global"})()
        self.last_probe_result = type(
            "Probe",
            (),
            {
                "endpoint": "/api/v1/events",
                "status_code": 404,
                "error_class": "http_404",
                "fallback_reason": "agent_endpoint_not_available",
            },
        )()


class _CompatibilityModeManager:
    def decide(self, snapshot, *, health_report=None, feed_state=None):
        return ModeDecision(
            mode=AgentMode.SUPPORT,
            eligible_for_relay=False,
            compatibility_mode=True,
            reasons=("compatibility:global", "support_ready"),
        )


def test_shadow_selftest_runner_builds_evidence_pack():
    runner = ShadowSelfTestRunner(
        ShadowSelfTestConfig(
            base_url="http://localhost:7770",
            api_key="secret",
            agent_id="agent-1",
            polls=3,
        ),
        event_adapter=_FakeAdapter(),
        inbox_supervisor=_FakeInboxSupervisor(),
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )

    result = runner.run()

    assert result["feed_probe"]["feed_source"] == "agent_scoped"
    assert result["event_feed"]["cursor_progression"] == [10, 12, 12, 15]
    assert result["event_feed"]["empty_polls"] == 1
    assert result["heartbeat"]["event_subscription_source"] == "default"
    assert result["inbox"]["sample_item"]["id"] == "INB1"
    assert result["mode_decision"]["mode"] == "support"
    assert result["validation"]["status"] == "full_pass"
    assert result["validation"]["full_pass"] is True
    assert result["validation"]["compatibility_pass"] is False


def test_shadow_selftest_runner_includes_channel_routing_when_configured():
    runner = ShadowSelfTestRunner(
        ShadowSelfTestConfig(
            base_url="http://localhost:7770",
            api_key="secret",
            agent_id="agent-1",
            polls=1,
            watched_channel_ids=("Cagent",),
            agent_handles=("pilot_agent",),
            agent_user_ids=("user_agent",),
            require_direct_address=True,
            channel_validation_limit=3,
        ),
        event_adapter=_FakeAdapter(),
        inbox_supervisor=_FakeInboxSupervisor(),
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )
    runner._fetch_channel_messages = lambda channel_id, limit: [
        {
            "id": "M1",
            "channel_id": channel_id,
            "user_id": "user_human",
            "content": "@Pilot_Agent please take this next step",
        },
        {
            "id": "M2",
            "channel_id": channel_id,
            "user_id": "user_human",
            "content": "ambient note without addressability",
        },
    ]

    result = runner.run()

    assert result["channel_routing"]["enabled"] is True
    assert result["channel_routing"]["evaluated_messages"] == 2
    assert result["channel_routing"]["actionable_count"] == 1
    assert result["channel_routing"]["non_actionable_count"] == 1
    assert result["channel_routing"]["reason_counts"]["actionable"] == 1
    assert result["channel_routing"]["reason_counts"]["not_addressed"] == 1
    assert result["channel_routing"]["samples"][0]["message_id"] == "M1"
    assert result["channel_routing"]["samples"][0]["routing_reasons"] == ["direct_mention"]


def test_shadow_selftest_runner_marks_compatibility_pass():
    runner = ShadowSelfTestRunner(
        ShadowSelfTestConfig(
            base_url="http://localhost:7770",
            api_key="secret",
            agent_id="agent-1",
            polls=1,
        ),
        event_adapter=_CompatibilityAdapter(),
        inbox_supervisor=_FakeInboxSupervisor(),
        metrics=_FakeMetrics(),
        mode_manager=_CompatibilityModeManager(),
    )

    result = runner.run()

    assert result["validation"]["status"] == "compatibility_pass"
    assert result["validation"]["compatibility_pass"] is True
    assert "feed_fallback:agent_endpoint_not_available" in result["validation"]["warnings"]


def test_shadow_selftest_cli_returns_nonzero_when_min_validation_not_met(monkeypatch):
    class _Runner:
        def __init__(self, config):
            self.config = config

        def run(self):
            return {
                "validation": {
                    "status": "compatibility_pass",
                }
            }

        def close(self):
            return None

    monkeypatch.setattr("canopykit.__main__.ShadowSelfTestRunner", _Runner)

    rc = cli_main(
        [
            "shadow-selftest",
            "--base-url",
            "http://localhost:7770",
            "--api-key",
            "secret",
            "--agent-id",
            "agent-1",
            "--min-validation-level",
            "full_pass",
        ]
    )

    assert rc == 1


def test_build_shadow_config_accepts_env_api_key(monkeypatch):
    monkeypatch.setenv("CANOPYKIT_API_KEY", "from-env")
    config = build_shadow_config(
        base_url="http://localhost:7770",
        api_key="",
        api_key_file="",
        config=None,
        agent_id="agent-2",
        data_dir="data/canopykit",
        poll_interval_seconds=0,
        heartbeat_fallback_seconds=30,
        request_timeout_seconds=10.0,
        polls=2,
        event_limit=10,
        inbox_limit=3,
    )
    assert config.api_key == "from-env"


def test_build_shadow_config_propagates_channel_config():
    cfg = CanopyKitConfig(
        api_key="secret",
        watched_channel_ids=("Cagent",),
        agent_handles=("pilot_agent",),
        agent_user_ids=("user_agent",),
        require_direct_address=False,
    )
    shadow = build_shadow_config(
        base_url="",
        api_key="",
        api_key_file="",
        config=cfg,
        agent_id="agent-9",
        data_dir="data/canopykit",
        poll_interval_seconds=0,
        heartbeat_fallback_seconds=30,
        request_timeout_seconds=10.0,
        polls=2,
        event_limit=10,
        inbox_limit=3,
    )
    assert shadow.watched_channel_ids == ("Cagent",)
    assert shadow.agent_handles == ("pilot_agent",)
    assert shadow.agent_user_ids == ("user_agent",)
    assert shadow.require_direct_address is False


def test_build_shadow_config_requires_api_key():
    try:
        build_shadow_config(
            base_url="http://localhost:7770",
            api_key="",
            api_key_file="",
            config=None,
            agent_id="agent-3",
            data_dir="data/canopykit",
            poll_interval_seconds=0,
            heartbeat_fallback_seconds=30,
            request_timeout_seconds=10.0,
            polls=2,
            event_limit=10,
            inbox_limit=3,
        )
    except ValueError as exc:
        assert "API key required" in str(exc)
    else:
        raise AssertionError("Expected ValueError when no API key is provided")


class _UnavailableFamiliesAdapter(_FakeAdapter):
    """Adapter whose heartbeat reports dm.message.created as auth-blocked."""

    def fetch_heartbeat(self):
        return {
            "needs_action": False,
            "pending_inbox": 0,
            "unacked_mentions": 0,
            "workspace_event_seq": 5,
            "event_subscription_source": "default",
            "event_subscription_count": 5,
            "event_subscription_types": [
                "mention.created",
                "inbox.item.created",
            ],
            "event_subscription_unavailable_types": [
                "dm.message.created",
                "dm.message.edited",
                "dm.message.deleted",
            ],
        }


def test_shadow_selftest_captures_unavailable_message_families():
    """Heartbeat reports auth-blocked dm.message.* families in the output pack."""
    adapter = _UnavailableFamiliesAdapter()
    adapter._polls = [([], None), ([], None), ([], None)]

    runner = ShadowSelfTestRunner(
        ShadowSelfTestConfig(
            base_url="http://localhost:7770",
            api_key="secret",
            agent_id="agent-1",
            polls=3,
        ),
        event_adapter=adapter,
        inbox_supervisor=_FakeInboxSupervisor(),
        metrics=_FakeMetrics(),
        mode_manager=_FakeModeManager(),
    )

    result = runner.run()

    unavailable = result["heartbeat"]["event_subscription_unavailable_types"]
    assert "dm.message.created" in unavailable
    assert "dm.message.edited" in unavailable
    assert "dm.message.deleted" in unavailable
    assert result["heartbeat"]["event_subscription_count"] == 5
    assert set(result["heartbeat"]["event_subscription_types"]) == {
        "mention.created",
        "inbox.item.created",
    }
