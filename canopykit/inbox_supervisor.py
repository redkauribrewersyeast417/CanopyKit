"""Concrete InboxSupervisor implementation for CanopyKit.

This module stays strictly in the closed-world layer:
- fetch current coordination state from Canopy agent endpoints
- preserve actionable inbox semantics (`pending` and `seen`)
- require evidence-bearing completion

It does not try to infer intent from free-form text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import requests

from .runtime import AgentMode, CoordinationSnapshot

ACTIONABLE_STATUSES = frozenset({"pending", "seen"})


@dataclass(slots=True)
class InboxSupervisorConfig:
    """Configuration for the Canopy inbox supervisor."""

    base_url: str
    api_key: str
    request_timeout_seconds: float = 10.0
    inbox_limit: int = 50


@dataclass(slots=True)
class InboxPatchResult:
    """Result of a best-effort inbox patch attempt."""

    applied: bool
    retryable: bool = False
    status_code: int = 0
    error_class: str = ""
    message: str = ""


class CanopyInboxSupervisor:
    """Concrete InboxSupervisor bound to the live Canopy agent API."""

    def __init__(self, config: InboxSupervisorConfig) -> None:
        self._config = config

    def snapshot(self) -> CoordinationSnapshot:
        """Return a current coordination snapshot from Canopy."""
        heartbeat = self._fetch_heartbeat()
        inbox_items = self._fetch_inbox_items()

        pending_inbox = sum(
            1
            for item in inbox_items
            if str(item.get("status") or "").strip().lower() in ACTIONABLE_STATUSES
        )

        poll_hint = _coerce_int(
            heartbeat.get("poll_hint_seconds") or heartbeat.get("poll_interval_seconds")
        )
        last_event_cursor_seen = _coerce_int(
            heartbeat.get("workspace_event_seq") or heartbeat.get("last_event_seq")
        )

        return CoordinationSnapshot(
            wake_source="inbox" if pending_inbox > 0 else "heartbeat",
            canopy_poll_interval_seconds=poll_hint,
            blind_window_seconds=poll_hint,
            pending_inbox=pending_inbox,
            unacked_mentions=int(heartbeat.get("unacked_mentions") or 0),
            last_event_cursor_seen=last_event_cursor_seen,
            mode=_resolve_mode(heartbeat),
        )

    def mark_seen(self, inbox_id: str) -> InboxPatchResult:
        """Mark an inbox item as seen while keeping it actionable."""
        return self._patch_inbox(inbox_id, {"status": "seen"}, best_effort=True)

    def mark_completed(self, inbox_id: str, completion_ref: Mapping[str, Any]) -> None:
        """Mark an inbox item completed with required evidence."""
        if not completion_ref:
            raise ValueError(
                "completion_ref must be a non-empty mapping; refusing to complete without evidence"
            )
        result = self._patch_inbox(
            inbox_id,
            {"status": "completed", "completion_ref": dict(completion_ref)},
        )
        if not result.applied:
            raise RuntimeError(
                f"failed to complete inbox item {inbox_id}: "
                f"{result.status_code or result.error_class or 'unknown_error'}"
            )

    def actionable_items(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return actionable inbox items for evidence and operator review."""
        items = self._fetch_inbox_items(limit=limit)
        return [
            item
            for item in items
            if str(item.get("status") or "").strip().lower() in ACTIONABLE_STATUSES
        ]

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._config.api_key}

    def _fetch_heartbeat(self) -> dict[str, Any]:
        response = requests.get(
            f"{self._config.base_url}/api/v1/agents/me/heartbeat",
            headers=self._headers(),
            timeout=self._config.request_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def _fetch_inbox_items(self, *, limit: Optional[int] = None) -> list[dict[str, Any]]:
        response = requests.get(
            f"{self._config.base_url}/api/v1/agents/me/inbox",
            headers=self._headers(),
            params={"limit": limit or self._config.inbox_limit},
            timeout=self._config.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return list(data.get("items") or [])

    def _patch_inbox(
        self,
        inbox_id: str,
        payload: dict[str, Any],
        *,
        best_effort: bool = False,
    ) -> InboxPatchResult:
        try:
            response = requests.patch(
                f"{self._config.base_url}/api/v1/agents/me/inbox/{inbox_id}",
                headers=self._headers(),
                json=payload,
                timeout=self._config.request_timeout_seconds,
            )
            response.raise_for_status()
            return InboxPatchResult(applied=True, status_code=response.status_code)
        except requests.HTTPError as exc:
            response = exc.response
            status_code = int(response.status_code) if response is not None else 0
            retryable = status_code in {429, 500, 502, 503, 504}
            if best_effort:
                return InboxPatchResult(
                    applied=False,
                    retryable=retryable,
                    status_code=status_code,
                    error_class=exc.__class__.__name__,
                    message=str(exc),
                )
            raise
        except requests.RequestException as exc:
            if best_effort:
                return InboxPatchResult(
                    applied=False,
                    retryable=True,
                    error_class=exc.__class__.__name__,
                    message=str(exc),
                )
            raise


def _resolve_mode(heartbeat: Mapping[str, Any]) -> AgentMode:
    raw = str(heartbeat.get("mode") or "").strip().lower()
    if not raw:
        return AgentMode.BACKGROUND
    try:
        return AgentMode(raw)
    except ValueError:
        return AgentMode.BACKGROUND


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ACTIONABLE_STATUSES",
    "InboxPatchResult",
    "InboxSupervisorConfig",
    "CanopyInboxSupervisor",
]
