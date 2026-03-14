"""Deterministic routing from channel events to addressed work items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

from .channel_bridge import ChannelBridge, ChannelRoutingDecision


CHANNEL_EVENT_TYPES = (
    "channel.message.created",
    "channel.message.edited",
)


@dataclass(slots=True, frozen=True)
class ChannelTaskCandidate:
    event_type: str
    channel_id: str
    message_id: str
    content: str
    author_user_id: str
    routing: ChannelRoutingDecision


@dataclass(slots=True, frozen=True)
class ChannelRouteOutcome:
    actionable: bool
    reason: str
    task: Optional[ChannelTaskCandidate] = None


class ChannelEventRouter:
    """Resolve channel events into deterministic addressed work items."""

    def __init__(self, bridge: ChannelBridge):
        self.bridge = bridge

    def route_event(
        self,
        event: Mapping[str, Any],
        message_resolver: Callable[[str, str], Optional[Mapping[str, Any]]],
    ) -> ChannelRouteOutcome:
        event_type = str(event.get("event_type") or "")
        if event_type not in CHANNEL_EVENT_TYPES:
            return ChannelRouteOutcome(False, "event_type_not_supported")

        channel_id = str(event.get("channel_id") or event.get("payload", {}).get("channel_id") or "")
        message_id = str(event.get("message_id") or event.get("payload", {}).get("message_id") or "")
        if not channel_id or not message_id:
            return ChannelRouteOutcome(False, "missing_identifiers")

        message = message_resolver(channel_id, message_id)
        if not message:
            return ChannelRouteOutcome(False, "message_not_found")

        routing = self.bridge.evaluate_message(message)
        if not routing.actionable:
            return ChannelRouteOutcome(False, routing.reasons[0])

        task = ChannelTaskCandidate(
            event_type=event_type,
            channel_id=channel_id,
            message_id=message_id,
            content=str(message.get("content") or ""),
            author_user_id=str(message.get("user_id") or ""),
            routing=routing,
        )
        return ChannelRouteOutcome(True, "actionable", task=task)

    def route_events(
        self,
        events: Iterable[Mapping[str, Any]],
        message_resolver: Callable[[str, str], Optional[Mapping[str, Any]]],
    ) -> list[ChannelRouteOutcome]:
        return [self.route_event(event, message_resolver) for event in events]


__all__ = [
    "CHANNEL_EVENT_TYPES",
    "ChannelEventRouter",
    "ChannelRouteOutcome",
    "ChannelTaskCandidate",
]
