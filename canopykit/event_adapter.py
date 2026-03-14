"""
CanopyKit Event Adapter - Polls Canopy event feeds.

Implements cursor persistence, heartbeat fallback, bounded polling, and
compatibility fallback between the intended agent-scoped feed and the older
global workspace feed.
"""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


class FeedSource(str, Enum):
    AGENT_SCOPED = "agent_scoped"
    GLOBAL = "global"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class FeedProbeResult:
    endpoint: str
    status_code: int
    error_class: str
    active_feed_source: str
    fallback_reason: str = ""


@dataclass(slots=True)
class EventCursorState:
    """State for tracking cursor position."""
    last_seq: int = 0


@dataclass(slots=True)
class AgentEventFeedConfig:
    """Configuration for the event adapter."""
    base_url: str
    api_key: str
    agent_id: str
    limit: int = 50
    poll_interval_seconds: int = 2
    heartbeat_fallback_seconds: int = 30
    backoff_initial_seconds: float = 2.0
    backoff_max_seconds: float = 30.0
    request_timeout_seconds: float = 10.0
    data_dir: str = "data/canopykit"


class SQLiteCursorStore:
    """
    SQLite-based cursor persistence.
    
    Stores last_seq in data/canopykit/cursor.db with INTEGER column.
    Creates table and database on first access.
    """
    
    def __init__(self, data_dir: str, agent_id: str):
        self.data_dir = Path(data_dir)
        self.agent_id = agent_id
        self.db_path = self.data_dir / "cursor.db"
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()
    
    def _ensure_schema(self) -> None:
        """Create database and table if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cursors (
                agent_id TEXT PRIMARY KEY,
                last_seq INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
        return self._conn
    
    def load(self) -> EventCursorState:
        """Load cursor state from SQLite."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT last_seq FROM cursors WHERE agent_id = ?",
            (self.agent_id,)
        ).fetchone()
        
        if row is None:
            # Default to 0 if no row exists
            return EventCursorState(last_seq=0)
        
        return EventCursorState(last_seq=row[0])
    
    def save(self, state: EventCursorState) -> None:
        """Persist cursor state to SQLite."""
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO cursors (agent_id, last_seq, updated_at)
               VALUES (?, ?, datetime('now'))""",
            (self.agent_id, state.last_seq)
        )
        conn.commit()


class EventAdapter:
    """
    Event adapter for Canopy agent event feed.
    
    Polls /api/v1/agents/me/events with cursor persistence,
    heartbeat fallback, and exponential backoff.

    If the preferred agent-scoped endpoint is unavailable on an older Canopy
    node, the adapter can fall back to /api/v1/events and expose that fact
    explicitly to operators.
    """
    
    DEFAULT_EVENT_TYPES = (
        "dm.message.created",
        "dm.message.edited",
        "dm.message.deleted",
        "mention.created",
        "mention.acknowledged",
        "inbox.item.created",
        "inbox.item.updated",
        "attachment.available",
    )

    AGENT_EVENTS_PATH = "/api/v1/agents/me/events"
    GLOBAL_EVENTS_PATH = "/api/v1/events"
    
    def __init__(self, config: AgentEventFeedConfig):
        self.config = config
        self._cursor_store = SQLiteCursorStore(config.data_dir, config.agent_id)
        self._cursor = self._cursor_store.load()
        self._consecutive_empty_polls = 0
        self._current_backoff: Optional[float] = None
        self._last_poll_time: float = 0
        self._feed_source = FeedSource.UNKNOWN
        self._last_probe_result: Optional[FeedProbeResult] = None
    
    @property
    def cursor(self) -> int:
        """Current cursor position."""
        return self._cursor.last_seq

    @property
    def feed_source(self) -> FeedSource:
        return self._feed_source

    @property
    def last_probe_result(self) -> Optional[FeedProbeResult]:
        return self._last_probe_result

    @property
    def current_backoff(self) -> Optional[float]:
        return self._current_backoff
    
    def poll(
        self,
        types: Optional[Iterable[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """
        Poll for new events after cursor.
        
        Args:
            types: Optional event type filter
            
        Returns:
            Tuple of (items, next_after_seq) or ([], None) on empty
        """
        if self._feed_source is FeedSource.UNKNOWN:
            self.probe_feed_source()

        # Calculate wait time based on backoff or normal interval
        wait_time = self._get_wait_time()
        if wait_time > 0:
            time.sleep(wait_time)
        
        try:
            response = self._fetch_events(types)
            items, next_seq = self._parse_response(response)
            self._current_backoff = None
            
            if items:
                # Successful items: immediate process, reset backoff
                self._consecutive_empty_polls = 0
                
                # Persist cursor only when items > 0 and next_after_seq present
                if next_seq is not None:
                    self._cursor.last_seq = next_seq
                    self._cursor_store.save(self._cursor)
                
                return items, next_seq
            else:
                # Empty response: keep cursor unchanged
                self._consecutive_empty_polls += 1
                return [], None
                
        except requests.exceptions.HTTPError as e:
            self._handle_http_error(e)
            return [], None
        except requests.exceptions.ConnectionError:
            # Linear backoff 5s on connection error
            self._current_backoff = 5.0
            return [], None
    
    def _get_wait_time(self) -> float:
        """Calculate wait time before next poll."""
        if self._current_backoff is not None:
            return self._current_backoff
        
        elapsed = time.time() - self._last_poll_time
        remaining = self.config.poll_interval_seconds - elapsed
        return max(0, remaining)
    
    def _fetch_events(
        self,
        types: Optional[Iterable[str]] = None,
    ) -> requests.Response:
        """Fetch events from the active Canopy feed source."""
        headers = {"X-API-Key": self.config.api_key}
        params = {"limit": self.config.limit}
        
        # Cursor = 0: first poll, no after_seq parameter
        if self._cursor.last_seq > 0:
            params["after_seq"] = self._cursor.last_seq
        
        event_types = tuple(types) if types is not None else self.DEFAULT_EVENT_TYPES
        if event_types:
            params["types"] = ",".join(event_types)

        response = self._request_events(self._feed_source, params=params)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if self._feed_source is FeedSource.AGENT_SCOPED and status_code == 404:
                self._feed_source = FeedSource.GLOBAL
                self._last_probe_result = FeedProbeResult(
                    endpoint=self.AGENT_EVENTS_PATH,
                    status_code=404,
                    error_class="http_404",
                    active_feed_source=self._feed_source.value,
                    fallback_reason="agent_endpoint_not_available",
                )
                response = self._request_events(self._feed_source, params=params)
                response.raise_for_status()
            else:
                raise
        
        self._last_poll_time = time.time()
        return response

    def _request_events(self, feed_source: FeedSource, *, params: Dict[str, Any]) -> requests.Response:
        path = self.AGENT_EVENTS_PATH if feed_source is FeedSource.AGENT_SCOPED else self.GLOBAL_EVENTS_PATH
        url = f"{self.config.base_url}{path}"
        return requests.get(
            url,
            headers={"X-API-Key": self.config.api_key},
            params=params,
            timeout=self.config.request_timeout_seconds,
        )
    
    def _parse_response(
        self,
        response: requests.Response,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """
        Parse API response.
        
        Args:
            response: HTTP response
            
        Returns:
            Tuple of (items, next_after_seq)
        """
        data = response.json()
        
        # Response shape: {"items": [...], "next_after_seq": N}
        items = data.get("items", [])
        next_seq = data.get("next_after_seq")
        
        # next_after_seq may be null/missing if no items returned
        # Only return valid next_seq when items > 0
        if not items:
            return [], None
        
        return items, next_seq
    
    def _handle_http_error(self, error: requests.exceptions.HTTPError) -> None:
        """Handle HTTP errors with appropriate backoff."""
        status = error.response.status_code if error.response else 500
        
        if status in (429, 503):
            # Exponential backoff starting at 2s, max 30s
            if self._current_backoff is None:
                self._current_backoff = self.config.backoff_initial_seconds
            else:
                self._current_backoff = min(
                    self._current_backoff * 2,
                    self.config.backoff_max_seconds
                )
        else:
            # Other errors: linear backoff 5s
            self._current_backoff = 5.0

    def probe_feed_source(self) -> FeedSource:
        """Probe the preferred and fallback event feeds.

        Only explicit 404 on the preferred endpoint triggers compatibility
        fallback. Other failures remain explicit so the runtime does not hide
        transport or auth problems behind a false fallback.
        """
        preferred = self._probe_endpoint(self.AGENT_EVENTS_PATH)
        if preferred.status_code == 200:
            self._feed_source = FeedSource.AGENT_SCOPED
            self._last_probe_result = FeedProbeResult(
                endpoint=self.AGENT_EVENTS_PATH,
                status_code=200,
                error_class=preferred.error_class,
                active_feed_source=self._feed_source.value,
            )
            return self._feed_source

        if preferred.status_code == 404:
            fallback = self._probe_endpoint(self.GLOBAL_EVENTS_PATH)
            if fallback.status_code == 200:
                self._feed_source = FeedSource.GLOBAL
                self._last_probe_result = FeedProbeResult(
                    endpoint=self.GLOBAL_EVENTS_PATH,
                    status_code=200,
                    error_class=fallback.error_class,
                    active_feed_source=self._feed_source.value,
                    fallback_reason="agent_endpoint_not_available",
                )
                return self._feed_source

            self._feed_source = FeedSource.UNKNOWN
            self._last_probe_result = FeedProbeResult(
                endpoint=self.GLOBAL_EVENTS_PATH,
                status_code=fallback.status_code,
                error_class=fallback.error_class,
                active_feed_source=self._feed_source.value,
                fallback_reason="global_endpoint_unavailable",
            )
            return self._feed_source

        self._feed_source = FeedSource.UNKNOWN
        self._last_probe_result = FeedProbeResult(
            endpoint=self.AGENT_EVENTS_PATH,
            status_code=preferred.status_code,
            error_class=preferred.error_class,
            active_feed_source=self._feed_source.value,
            fallback_reason="agent_probe_failed",
        )
        return self._feed_source

    def _probe_endpoint(self, path: str) -> FeedProbeResult:
        try:
            response = requests.get(
                f"{self.config.base_url}{path}",
                headers={"X-API-Key": self.config.api_key},
                params={"limit": 1},
                timeout=self.config.request_timeout_seconds,
            )
            error_class = f"http_{response.status_code}" if response.status_code >= 400 else ""
            return FeedProbeResult(
                endpoint=path,
                status_code=int(response.status_code),
                error_class=error_class,
                active_feed_source=self._feed_source.value,
            )
        except requests.exceptions.RequestException as exc:
            return FeedProbeResult(
                endpoint=path,
                status_code=0,
                error_class=exc.__class__.__name__,
                active_feed_source=self._feed_source.value,
            )
    
    def should_heartbeat_fallback(self) -> bool:
        """
        Check if should switch to heartbeat polling.
        
        Returns:
            True if N consecutive empty polls reached
        """
        # Switch when items=[] for heartbeat_fallback_seconds / poll_interval consecutive polls
        effective_poll_interval = max(1, self.config.poll_interval_seconds)
        threshold = max(
            1,
            math.ceil(
                self.config.heartbeat_fallback_seconds
                / effective_poll_interval
            ),
        )
        return self._consecutive_empty_polls >= threshold
    
    def fetch_heartbeat(self) -> Dict[str, Any]:
        """
        Fetch heartbeat as fallback.
        
        Returns:
            Heartbeat response data
        """
        url = f"{self.config.base_url}/api/v1/agents/me/heartbeat"
        headers = {"X-API-Key": self.config.api_key}
        
        response = requests.get(
            url,
            headers=headers,
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        
        # Return to event polling on first non-empty batch
        # (caller should check and reset consecutive_empty_polls)
        return response.json()
    
    def reset_cursor(self) -> None:
        """Reset cursor to 0 for fresh start."""
        self._cursor = EventCursorState(last_seq=0)
        self._cursor_store.save(self._cursor)
        self._consecutive_empty_polls = 0
        self._current_backoff = None
    
    def close(self) -> None:
        """Close database connection."""
        if self._cursor_store._conn is not None:
            self._cursor_store._conn.close()
            self._cursor_store._conn = None


# Convenience exports
__all__ = [
    "FeedSource",
    "FeedProbeResult",
    "EventCursorState",
    "AgentEventFeedConfig",
    "SQLiteCursorStore",
    "EventAdapter",
]
