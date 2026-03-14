from __future__ import annotations

from canopykit.channel_bridge import ChannelBridge, ChannelBridgeConfig
from canopykit.channel_router import ChannelEventRouter


def _router(**kwargs) -> ChannelEventRouter:
    cfg = ChannelBridgeConfig.from_iterables(
        agent_handles=kwargs.pop("agent_handles", ("Pilot_Agent",)),
        watched_channel_ids=kwargs.pop("watched_channel_ids", ("canopy-agent",)),
        agent_user_ids=kwargs.pop("agent_user_ids", ("user_agent_self",)),
        require_direct_address=kwargs.pop("require_direct_address", True),
        honor_structured_assignments=kwargs.pop("honor_structured_assignments", True),
        ignore_self_authored=kwargs.pop("ignore_self_authored", True),
    )
    return ChannelEventRouter(ChannelBridge(cfg))


def test_route_created_direct_mention_is_actionable():
    router = _router()
    message = {
        "message_id": "M1",
        "channel_id": "canopy-agent",
        "content": "@Pilot_Agent please run the next shadow test.",
        "user_id": "user_other",
    }

    outcome = router.route_event(
        {
            "event_type": "channel.message.created",
            "channel_id": "canopy-agent",
            "message_id": "M1",
        },
        lambda channel_id, message_id: message,
    )

    assert outcome.actionable is True
    assert outcome.reason == "actionable"
    assert outcome.task is not None
    assert outcome.task.message_id == "M1"
    assert "direct_mention" in outcome.task.routing.reasons


def test_route_edited_structured_assignment_is_actionable():
    router = _router()
    message = {
        "message_id": "M2",
        "channel_id": "canopy-agent",
        "content": "[task]\nowner: @Pilot_Agent\n[/task]",
        "user_id": "user_other",
    }

    outcome = router.route_event(
        {
            "event_type": "channel.message.edited",
            "payload": {
                "channel_id": "canopy-agent",
                "message_id": "M2",
            },
        },
        lambda channel_id, message_id: message,
    )

    assert outcome.actionable is True
    assert outcome.task is not None
    assert outcome.task.event_type == "channel.message.edited"
    assert "structured:owner" in outcome.task.routing.reasons


def test_route_unsupported_event_type_is_ignored():
    router = _router()

    outcome = router.route_event(
        {
            "event_type": "mention.created",
            "channel_id": "canopy-agent",
            "message_id": "M3",
        },
        lambda channel_id, message_id: None,
    )

    assert outcome.actionable is False
    assert outcome.reason == "event_type_not_supported"


def test_route_missing_identifiers_is_rejected():
    router = _router()

    outcome = router.route_event(
        {
            "event_type": "channel.message.created",
            "payload": {},
        },
        lambda channel_id, message_id: None,
    )

    assert outcome.actionable is False
    assert outcome.reason == "missing_identifiers"


def test_route_message_not_found_is_reported():
    router = _router()

    outcome = router.route_event(
        {
            "event_type": "channel.message.created",
            "channel_id": "canopy-agent",
            "message_id": "missing",
        },
        lambda channel_id, message_id: None,
    )

    assert outcome.actionable is False
    assert outcome.reason == "message_not_found"


def test_route_bridge_rejection_reason_is_preserved():
    router = _router()
    message = {
        "message_id": "M4",
        "channel_id": "canopy-agent",
        "content": "General team update with no direct tags.",
        "user_id": "user_other",
    }

    outcome = router.route_event(
        {
            "event_type": "channel.message.created",
            "channel_id": "canopy-agent",
            "message_id": "M4",
        },
        lambda channel_id, message_id: message,
    )

    assert outcome.actionable is False
    assert outcome.reason == "not_addressed"
