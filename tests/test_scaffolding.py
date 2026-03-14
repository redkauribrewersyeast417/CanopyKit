from canopykit import AgentMode, EventEnvelope
from canopykit.config import CanopyKitConfig
from canopykit.metrics import metric_names


def test_metric_names_include_core_metrics():
    names = metric_names()
    assert "event_to_seen_ms" in names
    assert "pending_inbox" in names


def test_default_config_is_localhost():
    cfg = CanopyKitConfig()
    assert cfg.base_url == "http://localhost:7770"
    assert cfg.event_poll_interval_seconds == 15


def test_runtime_types_import_cleanly():
    env = EventEnvelope(seq=1, event_type="mention.created")
    assert env.seq == 1
    assert AgentMode.RELAY_GRADE.value == "relay_grade"

