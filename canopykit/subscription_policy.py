"""Closed-world subscription scope policy for CanopyKit.

Subscriptions in CanopyKit are interest filters only. They must never widen
what an agent is allowed to see or process. This module keeps that rule in
deterministic code:

- requested scope is explicit
- authorized scope is explicit
- effective scope is the intersection of the two
- denied and idle reasons are visible to operators
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class SubscriptionScope:
    """Explicit scope for authorized or requested work."""

    channel_ids: FrozenSet[str] = field(default_factory=frozenset)
    task_ids: FrozenSet[str] = field(default_factory=frozenset)
    objective_ids: FrozenSet[str] = field(default_factory=frozenset)
    event_types: FrozenSet[str] = field(default_factory=frozenset)

    @classmethod
    def from_iterables(
        cls,
        *,
        channel_ids: Iterable[str] = (),
        task_ids: Iterable[str] = (),
        objective_ids: Iterable[str] = (),
        event_types: Iterable[str] = (),
    ) -> "SubscriptionScope":
        return cls(
            channel_ids=frozenset(str(item) for item in channel_ids if str(item).strip()),
            task_ids=frozenset(str(item) for item in task_ids if str(item).strip()),
            objective_ids=frozenset(str(item) for item in objective_ids if str(item).strip()),
            event_types=frozenset(str(item) for item in event_types if str(item).strip()),
        )

    def is_empty(self) -> bool:
        return not (self.channel_ids or self.task_ids or self.objective_ids or self.event_types)


@dataclass(frozen=True, slots=True)
class SubscriptionDecision:
    """Deterministic outcome of a subscription request."""

    requested_scope: SubscriptionScope
    authorized_scope: SubscriptionScope
    effective_scope: SubscriptionScope
    denied_scope: SubscriptionScope
    state: str
    reasons: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.state in {"active", "authorized_but_idle"}


def evaluate_subscription(
    requested_scope: SubscriptionScope,
    authorized_scope: SubscriptionScope,
) -> SubscriptionDecision:
    """Intersect requested scope with authorized scope and explain the result."""

    effective_scope = SubscriptionScope(
        channel_ids=requested_scope.channel_ids & authorized_scope.channel_ids,
        task_ids=requested_scope.task_ids & authorized_scope.task_ids,
        objective_ids=requested_scope.objective_ids & authorized_scope.objective_ids,
        event_types=requested_scope.event_types & authorized_scope.event_types,
    )

    denied_scope = SubscriptionScope(
        channel_ids=requested_scope.channel_ids - authorized_scope.channel_ids,
        task_ids=requested_scope.task_ids - authorized_scope.task_ids,
        objective_ids=requested_scope.objective_ids - authorized_scope.objective_ids,
        event_types=requested_scope.event_types - authorized_scope.event_types,
    )

    reasons: list[str] = []

    if requested_scope.is_empty():
        reasons.append("empty_request")
        return SubscriptionDecision(
            requested_scope=requested_scope,
            authorized_scope=authorized_scope,
            effective_scope=effective_scope,
            denied_scope=denied_scope,
            state="not_subscribed",
            reasons=tuple(reasons),
        )

    if not denied_scope.is_empty():
        if denied_scope.channel_ids:
            reasons.append("unauthorized_channels")
        if denied_scope.task_ids:
            reasons.append("unauthorized_tasks")
        if denied_scope.objective_ids:
            reasons.append("unauthorized_objectives")
        if denied_scope.event_types:
            reasons.append("unauthorized_event_types")

    if effective_scope.is_empty():
        reasons.append("no_authorized_match")
        return SubscriptionDecision(
            requested_scope=requested_scope,
            authorized_scope=authorized_scope,
            effective_scope=effective_scope,
            denied_scope=denied_scope,
            state="authorization_rejected",
            reasons=tuple(reasons),
        )

    if effective_scope != requested_scope:
        reasons.append("subscription_downgraded")

    if effective_scope == authorized_scope and denied_scope.is_empty():
        reasons.append("full_authorized_match")
    else:
        reasons.append("partial_authorized_match")

    return SubscriptionDecision(
        requested_scope=requested_scope,
        authorized_scope=authorized_scope,
        effective_scope=effective_scope,
        denied_scope=denied_scope,
        state="active",
        reasons=tuple(reasons),
    )


def subscription_diagnostics(decision: SubscriptionDecision) -> Mapping[str, object]:
    """Return an operator-facing diagnostic snapshot."""

    return {
        "state": decision.state,
        "accepted": decision.accepted,
        "reasons": list(decision.reasons),
        "requested_scope": {
            "channel_ids": sorted(decision.requested_scope.channel_ids),
            "task_ids": sorted(decision.requested_scope.task_ids),
            "objective_ids": sorted(decision.requested_scope.objective_ids),
            "event_types": sorted(decision.requested_scope.event_types),
        },
        "effective_scope": {
            "channel_ids": sorted(decision.effective_scope.channel_ids),
            "task_ids": sorted(decision.effective_scope.task_ids),
            "objective_ids": sorted(decision.effective_scope.objective_ids),
            "event_types": sorted(decision.effective_scope.event_types),
        },
        "denied_scope": {
            "channel_ids": sorted(decision.denied_scope.channel_ids),
            "task_ids": sorted(decision.denied_scope.task_ids),
            "objective_ids": sorted(decision.denied_scope.objective_ids),
            "event_types": sorted(decision.denied_scope.event_types),
        },
    }


__all__ = [
    "SubscriptionScope",
    "SubscriptionDecision",
    "evaluate_subscription",
    "subscription_diagnostics",
]
