from canopykit.subscription_policy import (
    SubscriptionScope,
    evaluate_subscription,
    subscription_diagnostics,
)


def test_empty_request_is_not_subscribed():
    requested = SubscriptionScope()
    authorized = SubscriptionScope.from_iterables(channel_ids=["C1"], event_types=["mention.created"])

    decision = evaluate_subscription(requested, authorized)

    assert decision.state == "not_subscribed"
    assert decision.accepted is False
    assert "empty_request" in decision.reasons


def test_subscription_only_narrows_authorized_scope():
    requested = SubscriptionScope.from_iterables(
        channel_ids=["C1", "C2"],
        task_ids=["T1", "T2"],
        event_types=["mention.created", "channel.message.created"],
    )
    authorized = SubscriptionScope.from_iterables(
        channel_ids=["C1", "C3"],
        task_ids=["T2", "T3"],
        event_types=["mention.created", "dm.message.created"],
    )

    decision = evaluate_subscription(requested, authorized)

    assert decision.state == "active"
    assert decision.accepted is True
    assert decision.effective_scope.channel_ids == frozenset({"C1"})
    assert decision.effective_scope.task_ids == frozenset({"T2"})
    assert decision.effective_scope.event_types == frozenset({"mention.created"})
    assert decision.denied_scope.channel_ids == frozenset({"C2"})
    assert decision.denied_scope.task_ids == frozenset({"T1"})
    assert decision.denied_scope.event_types == frozenset({"channel.message.created"})
    assert "subscription_downgraded" in decision.reasons


def test_fully_unauthorized_subscription_is_rejected():
    requested = SubscriptionScope.from_iterables(
        channel_ids=["C9"],
        objective_ids=["O7"],
        event_types=["channel.message.created"],
    )
    authorized = SubscriptionScope.from_iterables(
        channel_ids=["C1"],
        objective_ids=["O1"],
        event_types=["mention.created"],
    )

    decision = evaluate_subscription(requested, authorized)

    assert decision.state == "authorization_rejected"
    assert decision.accepted is False
    assert "unauthorized_channels" in decision.reasons
    assert "unauthorized_objectives" in decision.reasons
    assert "unauthorized_event_types" in decision.reasons
    assert "no_authorized_match" in decision.reasons


def test_diagnostics_surface_denied_and_effective_scope():
    requested = SubscriptionScope.from_iterables(
        channel_ids=["C1", "C9"],
        event_types=["mention.created", "channel.message.created"],
    )
    authorized = SubscriptionScope.from_iterables(
        channel_ids=["C1"],
        event_types=["mention.created"],
    )

    decision = evaluate_subscription(requested, authorized)
    diagnostics = subscription_diagnostics(decision)

    assert diagnostics["state"] == "active"
    assert diagnostics["accepted"] is True
    assert diagnostics["effective_scope"]["channel_ids"] == ["C1"]
    assert diagnostics["denied_scope"]["channel_ids"] == ["C9"]
    assert diagnostics["denied_scope"]["event_types"] == ["channel.message.created"]
