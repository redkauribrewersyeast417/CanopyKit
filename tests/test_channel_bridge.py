from __future__ import annotations

from canopykit.channel_bridge import ChannelBridge, ChannelBridgeConfig


def _bridge(**kwargs) -> ChannelBridge:
    cfg = ChannelBridgeConfig.from_iterables(
        agent_handles=kwargs.pop("agent_handles", ("Pilot_Agent",)),
        watched_channel_ids=kwargs.pop("watched_channel_ids", ("canopy-agent",)),
        agent_user_ids=kwargs.pop("agent_user_ids", ("user_agent_self",)),
        require_direct_address=kwargs.pop("require_direct_address", True),
        honor_structured_assignments=kwargs.pop("honor_structured_assignments", True),
        ignore_self_authored=kwargs.pop("ignore_self_authored", True),
    )
    return ChannelBridge(cfg)


def test_direct_mention_in_watched_channel_is_actionable():
    bridge = _bridge()

    decision = bridge.evaluate_message(
        {
            "channel_id": "canopy-agent",
            "user_id": "user_other",
            "content": "@Pilot_Agent please run the next shadow test.",
        }
    )

    assert decision.actionable is True
    assert "direct_mention" in decision.reasons
    assert decision.direct_mentions == ("pilot_agent",)


def test_structured_assignment_is_actionable_without_freeform_inference():
    bridge = _bridge()

    decision = bridge.evaluate_message(
        {
            "channel_id": "canopy-agent",
            "user_id": "user_other",
            "content": "[handoff]\nfrom: @Coordinator_Agent\nto: @Pilot_Agent\nnotes: Apply the patch.\n[/handoff]",
        }
    )

    assert decision.actionable is True
    assert "structured:to" in decision.reasons
    assert decision.structured_assignments["to"] == ("pilot_agent",)


def test_unaddressed_broadcast_is_ignored_by_default():
    bridge = _bridge()

    decision = bridge.evaluate_message(
        {
            "channel_id": "canopy-agent",
            "user_id": "user_other",
            "content": "We should probably improve initiative handling tomorrow.",
        }
    )

    assert decision.actionable is False
    assert decision.reasons == ("not_addressed",)


def test_non_watched_channel_is_ignored():
    bridge = _bridge()

    decision = bridge.evaluate_message(
        {
            "channel_id": "debug-hood",
            "user_id": "user_other",
            "content": "@Pilot_Agent can you review this?",
        }
    )

    assert decision.actionable is False
    assert decision.reasons == ("channel_not_watched",)


def test_self_authored_message_is_ignored():
    bridge = _bridge()

    decision = bridge.evaluate_message(
        {
            "channel_id": "canopy-agent",
            "user_id": "user_agent_self",
            "content": "@Pilot_Agent I finished the review.",
        }
    )

    assert decision.actionable is False
    assert decision.reasons == ("self_authored",)


def test_members_field_is_treated_as_closed_world_assignment():
    bridge = _bridge(agent_handles=("Reviewer_Agent",))

    decision = bridge.evaluate_message(
        {
            "channel_id": "canopy-agent",
            "user_id": "user_other",
            "content": "[request]\nmembers: @Pilot_Agent (assignee), @Reviewer_Agent (reviewer)\nrequest: Review the metrics output.\n[/request]",
        }
    )

    assert decision.actionable is True
    assert "structured:members" in decision.reasons
    assert decision.structured_assignments["members"] == (
        "pilot_agent",
        "reviewer_agent",
    )


def test_optional_broadcast_mode_can_accept_watched_channel_messages():
    bridge = _bridge(require_direct_address=False)

    decision = bridge.evaluate_message(
        {
            "channel_id": "canopy-agent",
            "user_id": "user_other",
            "content": "General team update with no direct tags.",
        }
    )

    assert decision.actionable is True
    assert decision.reasons == ("watch_channel_broadcast",)
