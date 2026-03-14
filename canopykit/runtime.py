"""Early CanopyKit runtime contracts.

This file defines the thin coordination interfaces we expect a Canopy-native
wrapper to own. It is intentionally small so runtime experiments can build on a
stable vocabulary before deeper implementation work starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Protocol


class AgentMode(str, Enum):
    BACKGROUND = "background"
    SUPPORT = "support"
    RELAY_GRADE = "relay_grade"


@dataclass(slots=True)
class EventEnvelope:
    seq: int
    event_type: str
    actor_user_id: Optional[str] = None
    target_user_id: Optional[str] = None
    channel_id: Optional[str] = None
    message_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CoordinationSnapshot:
    wake_source: str
    canopy_poll_interval_seconds: Optional[int]
    blind_window_seconds: Optional[int]
    pending_inbox: int
    unacked_mentions: int
    last_event_cursor_seen: Optional[int]
    mode: AgentMode


class EventAdapter(Protocol):
    def fetch_after(self, after_seq: Optional[int]) -> list[EventEnvelope]:
        """Return new Canopy events after the supplied cursor."""


class InboxSupervisor(Protocol):
    def snapshot(self) -> CoordinationSnapshot:
        """Return the current coordination snapshot for the agent."""

    def mark_seen(self, inbox_id: str) -> None:
        """Mark inbox work as observed without claiming completion."""

    def mark_completed(self, inbox_id: str, completion_ref: Mapping[str, Any]) -> None:
        """Mark inbox work complete and attach evidence."""


class ClaimWorker(Protocol):
    def claim(self, source_type: str, source_id: str) -> Dict[str, Any]:
        """Attempt to claim a work item."""

    def acknowledge(self, mention_id: str) -> Dict[str, Any]:
        """Acknowledge a mention after the related work is closed."""


class ArtifactValidator(Protocol):
    def validate(self, content: str) -> tuple[bool, list[str]]:
        """Return whether the outgoing artifact is structurally valid."""


class ModeManager(Protocol):
    def classify(self, snapshot: CoordinationSnapshot) -> AgentMode:
        """Assign a runtime mode from measured facts."""


class MetricsEmitter(Protocol):
    def record(self, metric: str, value: float, **labels: Any) -> None:
        """Record a coordination metric sample."""
