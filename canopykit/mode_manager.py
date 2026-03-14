"""Deterministic mode classification for CanopyKit.

This module keeps runtime mode selection in the closed-world layer.
It classifies from measured facts:
- feed source
- latency/health report
- backlog
- blind window
- blocked duration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .runtime import AgentMode, CoordinationSnapshot


@dataclass(frozen=True, slots=True)
class FeedSourceState:
    """Structured feed-source probe result.

    `fallback_reason` is a typed/status-style reason, not free-form prose.
    """

    endpoint: str
    status_code: int
    error_class: str
    active_feed_source: str
    fallback_reason: str = ""

    @property
    def compatibility_mode(self) -> bool:
        return self.active_feed_source != "agent_scoped"


@dataclass(frozen=True, slots=True)
class ModeDecision:
    mode: AgentMode
    eligible_for_relay: bool
    compatibility_mode: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ModeThresholds:
    relay_max_blind_window_seconds: int = 30
    support_max_blind_window_seconds: int = 300
    blocked_timeout_seconds: int = 120
    support_max_pending_inbox: int = 25
    support_max_unacked_mentions: int = 25
    relay_max_pending_inbox: int = 5
    relay_max_unacked_mentions: int = 10


class DefaultModeManager:
    """Closed-world mode manager based on runtime facts."""

    def __init__(self, thresholds: Optional[ModeThresholds] = None):
        self.thresholds = thresholds or ModeThresholds()

    def classify(
        self,
        snapshot: CoordinationSnapshot,
        *,
        health_report: Optional[Mapping[str, Any]] = None,
        feed_state: Optional[FeedSourceState] = None,
        blocked_duration_seconds: Optional[int] = None,
    ) -> AgentMode:
        return self.decide(
            snapshot,
            health_report=health_report,
            feed_state=feed_state,
            blocked_duration_seconds=blocked_duration_seconds,
        ).mode

    def decide(
        self,
        snapshot: CoordinationSnapshot,
        *,
        health_report: Optional[Mapping[str, Any]] = None,
        feed_state: Optional[FeedSourceState] = None,
        blocked_duration_seconds: Optional[int] = None,
    ) -> ModeDecision:
        reasons: list[str] = []
        thresholds = self.thresholds

        report_mode = str((health_report or {}).get("mode") or "").strip().lower()
        report_health = str((health_report or {}).get("health") or "").strip().lower()

        pending_inbox = int(snapshot.pending_inbox)
        unacked_mentions = int(snapshot.unacked_mentions)
        blind_window = (
            snapshot.blind_window_seconds if snapshot.blind_window_seconds is not None else 10**9
        )

        compatibility_mode = bool(feed_state and feed_state.compatibility_mode)

        if compatibility_mode:
            reasons.append(f"compatibility:{feed_state.active_feed_source}")
        else:
            reasons.append("feed:agent_scoped_or_unknown")

        if blocked_duration_seconds is not None and blocked_duration_seconds >= thresholds.blocked_timeout_seconds:
            reasons.append(f"blocked_too_long:{blocked_duration_seconds}s")
            return ModeDecision(
                mode=AgentMode.BACKGROUND,
                eligible_for_relay=False,
                compatibility_mode=compatibility_mode,
                reasons=tuple(reasons),
            )

        if report_health in {"unhealthy"}:
            reasons.append(f"health:{report_health}")
            return ModeDecision(
                mode=AgentMode.BACKGROUND,
                eligible_for_relay=False,
                compatibility_mode=compatibility_mode,
                reasons=tuple(reasons),
            )

        if blind_window <= thresholds.relay_max_blind_window_seconds:
            reasons.append(f"blind_window:{blind_window}s")
            if (
                not compatibility_mode
                and pending_inbox <= thresholds.relay_max_pending_inbox
                and unacked_mentions <= thresholds.relay_max_unacked_mentions
                and report_mode in {"relay", "relay_grade", ""}
                and report_health not in {"degraded", "recovering"}
            ):
                reasons.append("relay_ready")
                return ModeDecision(
                    mode=AgentMode.RELAY_GRADE,
                    eligible_for_relay=True,
                    compatibility_mode=False,
                    reasons=tuple(reasons),
                )

        if blind_window <= thresholds.support_max_blind_window_seconds:
            reasons.append(f"blind_window:{blind_window}s")
            if (
                pending_inbox <= thresholds.support_max_pending_inbox
                and unacked_mentions <= thresholds.support_max_unacked_mentions
                and report_health not in {"unhealthy"}
            ):
                reasons.append("support_ready")
                return ModeDecision(
                    mode=AgentMode.SUPPORT,
                    eligible_for_relay=False,
                    compatibility_mode=compatibility_mode,
                    reasons=tuple(reasons),
                )

        if report_mode in {"support"} and report_health in {"healthy", "degraded", "recovering"}:
            reasons.append(f"report_mode:{report_mode}")
            return ModeDecision(
                mode=AgentMode.SUPPORT,
                eligible_for_relay=False,
                compatibility_mode=compatibility_mode,
                reasons=tuple(reasons),
            )

        reasons.append("default:background")
        return ModeDecision(
            mode=AgentMode.BACKGROUND,
            eligible_for_relay=False,
            compatibility_mode=compatibility_mode,
            reasons=tuple(reasons),
        )
