"""Deterministic Canopy channel bridge for addressed agent work.

This bridge is intentionally narrow. It turns channel posts into actionable
agent work only when the post is explicitly addressed to the agent or assigns
the agent through closed-world structured fields. It does not try to infer
intent from arbitrary prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable, Mapping, Optional


HANDLE_RE = re.compile(r"@([A-Za-z0-9_.-]+)")
ASSIGNMENT_FIELDS = (
    "owner",
    "to",
    "next",
    "assignee",
    "reviewer",
    "members",
)


def _normalize_handle(value: str) -> str:
    return value.lstrip("@").strip().lower()


def _normalize_handles(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = _normalize_handle(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return tuple(ordered)


def _extract_handles(value: str) -> tuple[str, ...]:
    return _normalize_handles(match.group(1) for match in HANDLE_RE.finditer(value))


@dataclass(slots=True, frozen=True)
class ChannelBridgeConfig:
    agent_handles: tuple[str, ...]
    watched_channel_ids: frozenset[str] = field(default_factory=frozenset)
    agent_user_ids: frozenset[str] = field(default_factory=frozenset)
    require_direct_address: bool = True
    honor_structured_assignments: bool = True
    ignore_self_authored: bool = True

    @classmethod
    def from_iterables(
        cls,
        *,
        agent_handles: Iterable[str],
        watched_channel_ids: Iterable[str] = (),
        agent_user_ids: Iterable[str] = (),
        require_direct_address: bool = True,
        honor_structured_assignments: bool = True,
        ignore_self_authored: bool = True,
    ) -> "ChannelBridgeConfig":
        return cls(
            agent_handles=_normalize_handles(agent_handles),
            watched_channel_ids=frozenset(watched_channel_ids),
            agent_user_ids=frozenset(agent_user_ids),
            require_direct_address=require_direct_address,
            honor_structured_assignments=honor_structured_assignments,
            ignore_self_authored=ignore_self_authored,
        )


@dataclass(slots=True, frozen=True)
class ChannelRoutingDecision:
    actionable: bool
    reasons: tuple[str, ...]
    direct_mentions: tuple[str, ...] = ()
    structured_assignments: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


class ChannelBridge:
    """Turn explicitly addressed channel posts into deterministic work items."""

    def __init__(self, config: ChannelBridgeConfig):
        self.config = config

    def evaluate_message(
        self,
        message: Mapping[str, object],
    ) -> ChannelRoutingDecision:
        channel_id = str(message.get("channel_id") or "")
        user_id = str(message.get("user_id") or "")
        content = str(message.get("content") or "")

        reasons: list[str] = []

        if self.config.watched_channel_ids and channel_id not in self.config.watched_channel_ids:
            return ChannelRoutingDecision(False, ("channel_not_watched",))

        if self.config.ignore_self_authored and user_id and user_id in self.config.agent_user_ids:
            return ChannelRoutingDecision(False, ("self_authored",))

        direct_mentions = tuple(
            handle
            for handle in _extract_handles(content)
            if handle in self.config.agent_handles
        )
        structured_assignments = self._extract_structured_assignments(content)
        assignment_hits = tuple(
            field_name
            for field_name, handles in structured_assignments.items()
            if any(handle in self.config.agent_handles for handle in handles)
        )

        if direct_mentions:
            reasons.append("direct_mention")
        if assignment_hits:
            reasons.extend(f"structured:{field_name}" for field_name in assignment_hits)

        if self.config.require_direct_address and not reasons:
            return ChannelRoutingDecision(
                False,
                ("not_addressed",),
                direct_mentions=direct_mentions,
                structured_assignments=structured_assignments,
            )

        if reasons:
            return ChannelRoutingDecision(
                True,
                tuple(reasons),
                direct_mentions=direct_mentions,
                structured_assignments=structured_assignments,
            )

        return ChannelRoutingDecision(
            True,
            ("watch_channel_broadcast",),
            direct_mentions=direct_mentions,
            structured_assignments=structured_assignments,
        )

    def _extract_structured_assignments(self, content: str) -> dict[str, tuple[str, ...]]:
        if not self.config.honor_structured_assignments:
            return {}

        assignments: dict[str, tuple[str, ...]] = {}
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            field_name, remainder = line.split(":", 1)
            normalized_field = field_name.strip().lower()
            if normalized_field not in ASSIGNMENT_FIELDS:
                continue
            handles = _extract_handles(remainder)
            if handles:
                assignments[normalized_field] = handles
        return assignments


__all__ = [
    "ASSIGNMENT_FIELDS",
    "ChannelBridge",
    "ChannelBridgeConfig",
    "ChannelRoutingDecision",
]
