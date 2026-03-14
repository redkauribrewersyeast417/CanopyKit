"""Deterministic shadow-mode self-test runner for CanopyKit."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional

import requests

from .channel_bridge import ChannelBridge, ChannelBridgeConfig
from .channel_router import ChannelEventRouter
from .config import CanopyKitConfig
from .event_adapter import AgentEventFeedConfig, EventAdapter
from .inbox_supervisor import CanopyInboxSupervisor, InboxSupervisorConfig
from .metrics import MetricsEmitter, update_pending_inbox, update_unacked_mentions
from .mode_manager import DefaultModeManager, FeedSourceState


@dataclass(slots=True)
class ShadowSelfTestConfig:
    base_url: str
    api_key: str
    agent_id: str
    data_dir: str = "data/canopykit"
    poll_interval_seconds: int = 0
    heartbeat_fallback_seconds: int = 30
    request_timeout_seconds: float = 10.0
    polls: int = 3
    event_limit: int = 20
    inbox_limit: int = 5
    watched_channel_ids: tuple[str, ...] = ()
    agent_handles: tuple[str, ...] = ()
    agent_user_ids: tuple[str, ...] = ()
    require_direct_address: bool = True
    channel_validation_limit: int = 5


class ShadowSelfTestRunner:
    """Runs one bounded shadow-mode validation cycle against a live Canopy node."""

    DEFAULT_EVENT_TYPES = (
        "attachment.available",
        "dm.message.created",
        "dm.message.deleted",
        "dm.message.edited",
        "inbox.item.created",
        "inbox.item.updated",
        "mention.acknowledged",
        "mention.created",
    )

    def __init__(
        self,
        config: ShadowSelfTestConfig,
        *,
        event_adapter: Optional[EventAdapter] = None,
        inbox_supervisor: Optional[CanopyInboxSupervisor] = None,
        metrics: Optional[MetricsEmitter] = None,
        mode_manager: Optional[DefaultModeManager] = None,
    ):
        self.config = config
        self._event_adapter = event_adapter or EventAdapter(
            AgentEventFeedConfig(
                base_url=config.base_url,
                api_key=config.api_key,
                agent_id=config.agent_id,
                limit=config.event_limit,
                poll_interval_seconds=config.poll_interval_seconds,
                heartbeat_fallback_seconds=config.heartbeat_fallback_seconds,
                request_timeout_seconds=config.request_timeout_seconds,
                data_dir=config.data_dir,
            )
        )
        self._inbox_supervisor = inbox_supervisor or CanopyInboxSupervisor(
            InboxSupervisorConfig(
                base_url=config.base_url,
                api_key=config.api_key,
                request_timeout_seconds=config.request_timeout_seconds,
                inbox_limit=max(config.inbox_limit, 1),
            )
        )
        self._metrics = metrics or MetricsEmitter(agent_id=config.agent_id)
        self._mode_manager = mode_manager or DefaultModeManager()
        self._channel_router = ChannelEventRouter(
            ChannelBridge(
                ChannelBridgeConfig.from_iterables(
                    agent_handles=config.agent_handles,
                    watched_channel_ids=config.watched_channel_ids,
                    agent_user_ids=config.agent_user_ids,
                    require_direct_address=config.require_direct_address,
                )
            )
        )

    def run(self, types: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        event_types = tuple(types) if types is not None else self.DEFAULT_EVENT_TYPES

        feed_source = self._event_adapter.probe_feed_source()
        probe = self._event_adapter.last_probe_result
        cursor_progression = [self._event_adapter.cursor]
        total_polls = 0
        empty_polls = 0
        items_seen = 0

        for _ in range(self.config.polls):
            total_polls += 1
            items, _next_seq = self._event_adapter.poll(types=event_types)
            if items:
                items_seen += len(items)
            else:
                empty_polls += 1
            cursor_progression.append(self._event_adapter.cursor)

        heartbeat = self._event_adapter.fetch_heartbeat()
        snapshot = self._inbox_supervisor.snapshot()
        actionable_items = self._inbox_supervisor.actionable_items(limit=self.config.inbox_limit)

        update_pending_inbox(self._metrics, snapshot.pending_inbox)
        update_unacked_mentions(self._metrics, snapshot.unacked_mentions)
        health_report = self._metrics.health_report()

        feed_state = FeedSourceState(
            endpoint=probe.endpoint if probe else "",
            status_code=probe.status_code if probe else 0,
            error_class=probe.error_class if probe else "",
            active_feed_source=feed_source.value,
            fallback_reason=probe.fallback_reason if probe else "",
        )
        mode_decision = self._mode_manager.decide(
            snapshot,
            health_report=health_report,
            feed_state=feed_state,
        )

        sample_item = actionable_items[0] if actionable_items else None

        result = {
            "agent_id": self.config.agent_id,
            "base_url": self.config.base_url,
            "feed_probe": {
                "feed_source": feed_source.value,
                "endpoint": probe.endpoint if probe else "",
                "status_code": probe.status_code if probe else 0,
                "error_class": probe.error_class if probe else "",
                "fallback_reason": probe.fallback_reason if probe else "",
            },
            "event_feed": {
                "selected_types": list(event_types),
                "total_polls": total_polls,
                "empty_polls": empty_polls,
                "items_seen": items_seen,
                "cursor_progression": cursor_progression,
                "backoff_active": self._event_adapter.current_backoff is not None,
                "backoff_clear": self._event_adapter.current_backoff is None,
                "should_fallback": self._event_adapter.should_heartbeat_fallback(),
            },
            "heartbeat": {
                "needs_action": bool(heartbeat.get("needs_action")),
                "pending_inbox": int(heartbeat.get("pending_inbox") or 0),
                "unacked_mentions": int(heartbeat.get("unacked_mentions") or 0),
                "workspace_event_seq": heartbeat.get("workspace_event_seq"),
                "event_subscription_source": heartbeat.get("event_subscription_source"),
                "event_subscription_count": heartbeat.get("event_subscription_count"),
                "event_subscription_types": list(heartbeat.get("event_subscription_types") or []),
                "event_subscription_unavailable_types": list(
                    heartbeat.get("event_subscription_unavailable_types") or []
                ),
            },
            "inbox": {
                "actionable_count": snapshot.pending_inbox,
                "sample_item": {
                    "id": sample_item.get("id"),
                    "status": sample_item.get("status"),
                    "trigger_type": sample_item.get("trigger_type"),
                    "source_type": sample_item.get("source_type"),
                    "source_id": sample_item.get("source_id"),
                }
                if sample_item
                else None,
            },
            "health_report": health_report,
            "mode_decision": {
                "mode": mode_decision.mode.value,
                "eligible_for_relay": mode_decision.eligible_for_relay,
                "compatibility_mode": mode_decision.compatibility_mode,
                "reasons": list(mode_decision.reasons),
            },
        }
        channel_routing = self._run_channel_routing_validation()
        if channel_routing is not None:
            result["channel_routing"] = channel_routing
        result["validation"] = self._build_validation_summary(result)
        return result

    def _build_validation_summary(self, result: Mapping[str, Any]) -> Dict[str, Any]:
        feed_probe = dict(result.get("feed_probe") or {})
        event_feed = dict(result.get("event_feed") or {})
        mode_decision = dict(result.get("mode_decision") or {})
        channel_routing = result.get("channel_routing")

        feed_source = str(feed_probe.get("feed_source") or "unknown")
        fallback_reason = str(feed_probe.get("fallback_reason") or "")
        error_class = str(feed_probe.get("error_class") or "")
        endpoint = str(feed_probe.get("endpoint") or "")
        compatibility_mode = bool(mode_decision.get("compatibility_mode"))
        backoff_active = bool(event_feed.get("backoff_active"))
        should_fallback = bool(event_feed.get("should_fallback"))

        warnings: list[str] = []
        blocking_gaps: list[str] = []

        if not endpoint:
            blocking_gaps.append("feed_probe_missing_endpoint")
        if feed_source == "unknown":
            blocking_gaps.append("feed_source_unknown")
        if backoff_active:
            blocking_gaps.append("event_feed_backoff_active")
        if error_class and feed_source == "unknown":
            blocking_gaps.append(f"feed_probe_error:{error_class}")

        if should_fallback:
            warnings.append("heartbeat_fallback_triggered")

        if channel_routing and channel_routing.get("enabled") and not channel_routing.get("evaluated_messages"):
            warnings.append("channel_routing_enabled_but_no_messages_evaluated")

        if blocking_gaps:
            status = "failed"
        elif feed_source == "agent_scoped" and not compatibility_mode:
            status = "full_pass"
        else:
            status = "compatibility_pass"

        if status == "compatibility_pass":
            if fallback_reason:
                warnings.append(f"feed_fallback:{fallback_reason}")
            if feed_source != "agent_scoped":
                warnings.append(f"active_feed_source:{feed_source}")
            if compatibility_mode:
                warnings.append("mode_manager_marked_compatibility")

        if status == "full_pass":
            next_step = "Proceed to live shadow-mode validation and operator review."
        elif status == "compatibility_pass":
            next_step = "Accept only as interim validation; land agent-scoped feed parity before rollout."
        else:
            next_step = "Fix blocking gaps and rerun the canonical shadow self-test."

        return {
            "status": status,
            "full_pass": status == "full_pass",
            "compatibility_pass": status == "compatibility_pass",
            "blocking_gaps": blocking_gaps,
            "warnings": warnings,
            "next_step": next_step,
        }

    def _run_channel_routing_validation(self) -> Optional[Dict[str, Any]]:
        if not self.config.watched_channel_ids or not self.config.agent_handles:
            return None

        reason_counts: Dict[str, int] = {}
        samples: list[Dict[str, Any]] = []
        evaluated = 0
        actionable = 0
        non_actionable = 0

        for channel_id in self.config.watched_channel_ids:
            messages = self._fetch_channel_messages(channel_id, self.config.channel_validation_limit)
            message_index = {str(message.get("id") or ""): message for message in messages if message.get("id")}
            for message in messages:
                message_id = str(message.get("id") or "")
                if not message_id:
                    continue
                outcome = self._channel_router.route_event(
                    {
                        "event_type": "channel.message.created",
                        "channel_id": channel_id,
                        "message_id": message_id,
                    },
                    lambda resolved_channel_id, resolved_message_id: message_index.get(resolved_message_id)
                    if resolved_channel_id == channel_id
                    else None,
                )
                evaluated += 1
                reason_counts[outcome.reason] = reason_counts.get(outcome.reason, 0) + 1
                if outcome.actionable:
                    actionable += 1
                else:
                    non_actionable += 1
                if len(samples) < self.config.channel_validation_limit:
                    samples.append(
                        {
                            "channel_id": channel_id,
                            "message_id": message_id,
                            "actionable": outcome.actionable,
                            "reason": outcome.reason,
                            "routing_reasons": list(outcome.task.routing.reasons) if outcome.task else [],
                            "content_preview": str(message.get("content") or "")[:160],
                        }
                    )

        return {
            "enabled": True,
            "watched_channel_ids": list(self.config.watched_channel_ids),
            "agent_handles": list(self.config.agent_handles),
            "require_direct_address": self.config.require_direct_address,
            "evaluated_messages": evaluated,
            "actionable_count": actionable,
            "non_actionable_count": non_actionable,
            "reason_counts": reason_counts,
            "samples": samples,
        }

    def _fetch_channel_messages(self, channel_id: str, limit: int) -> list[Dict[str, Any]]:
        response = requests.get(
            f"{self.config.base_url}/api/v1/channels/{channel_id}/messages",
            headers={"X-API-Key": self.config.api_key},
            params={"limit": max(1, limit)},
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        messages = data.get("messages", [])
        if not isinstance(messages, list):
            return []
        return [message for message in messages if isinstance(message, Mapping)]

    def close(self) -> None:
        self._event_adapter.close()


def build_shadow_config(
    *,
    base_url: str,
    api_key: Optional[str],
    api_key_file: Optional[str],
    config: Optional[CanopyKitConfig],
    agent_id: str,
    data_dir: str,
    poll_interval_seconds: int,
    heartbeat_fallback_seconds: int,
    request_timeout_seconds: float,
    polls: int,
    event_limit: int,
    inbox_limit: int,
) -> ShadowSelfTestConfig:
    """Build a runnable shadow config from CLI and config defaults."""

    effective = config or CanopyKitConfig()
    resolved_api_key = (
        api_key
        or _read_api_key(api_key_file)
        or effective.api_key
        or os.environ.get("CANOPYKIT_API_KEY", "")
    ).strip()
    if not resolved_api_key:
        raise ValueError("API key required; pass --api-key, --api-key-file, config.api_key, or CANOPYKIT_API_KEY")

    return ShadowSelfTestConfig(
        base_url=base_url or effective.base_url,
        api_key=resolved_api_key,
        agent_id=agent_id,
        data_dir=data_dir,
        poll_interval_seconds=max(0, poll_interval_seconds),
        heartbeat_fallback_seconds=max(1, heartbeat_fallback_seconds),
        request_timeout_seconds=max(0.1, request_timeout_seconds),
        polls=max(1, polls),
        event_limit=max(1, event_limit),
        inbox_limit=max(1, inbox_limit),
        watched_channel_ids=tuple(effective.watched_channel_ids),
        agent_handles=tuple(effective.agent_handles),
        agent_user_ids=tuple(effective.agent_user_ids),
        require_direct_address=bool(effective.require_direct_address),
    )


def _read_api_key(path: Optional[str]) -> str:
    if not path:
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


__all__ = [
    "ShadowSelfTestConfig",
    "ShadowSelfTestRunner",
    "build_shadow_config",
]
