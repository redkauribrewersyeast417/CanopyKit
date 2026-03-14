"""Configuration vocabulary for CanopyKit."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(slots=True)
class CanopyKitConfig:
    base_url: str = "http://localhost:7770"
    api_key: str = ""
    event_poll_interval_seconds: int = 15
    heartbeat_fallback_seconds: int = 60
    inbox_limit: int = 50
    claim_ttl_seconds: int = 120
    backlog_ceiling: int = 100
    watched_channel_ids: tuple[str, ...] = ()
    agent_handles: tuple[str, ...] = ()
    agent_user_ids: tuple[str, ...] = ()
    require_direct_address: bool = True
    
    # Hot-reload support
    _config_path: Optional[str] = None
    _last_reload_ms: int = 0
    _reload_interval_ms: int = 30000  # 30 seconds default

    def to_dict(self) -> Dict[str, Any]:
        """Export config as dictionary (excludes internal fields)."""
        d = asdict(self)
        # Remove internal fields
        d.pop("_config_path", None)
        d.pop("_last_reload_ms", None)
        d.pop("_reload_interval_ms", None)
        return d

    def to_json(self) -> str:
        """Export config as JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "CanopyKitConfig":
        """Load config from JSON string."""
        data = json.loads(json_str)
        # Filter to known fields
        return cls(
            base_url=data.get("base_url", "http://localhost:7770"),
            api_key=data.get("api_key", ""),
            event_poll_interval_seconds=data.get("event_poll_interval_seconds", 15),
            heartbeat_fallback_seconds=data.get("heartbeat_fallback_seconds", 60),
            inbox_limit=data.get("inbox_limit", 50),
            claim_ttl_seconds=data.get("claim_ttl_seconds", 120),
            backlog_ceiling=data.get("backlog_ceiling", 100),
            watched_channel_ids=tuple(data.get("watched_channel_ids", ())),
            agent_handles=tuple(data.get("agent_handles", ())),
            agent_user_ids=tuple(data.get("agent_user_ids", ())),
            require_direct_address=data.get("require_direct_address", True),
        )

    @classmethod
    def from_file(cls, path: Path) -> "CanopyKitConfig":
        """Load config from JSON file."""
        with open(path, "r") as f:
            config = cls.from_json(f.read())
            config._config_path = str(path)
            config._last_reload_ms = int(time.time() * 1000)
            return config

    def save(self, path: Optional[Path] = None) -> None:
        """Save config to JSON file."""
        target = path or Path(self._config_path) if self._config_path else None
        if target is None:
            raise ValueError("No config path specified")
        with open(target, "w") as f:
            f.write(self.to_json())

    def reload_if_changed(self) -> bool:
        """
        Check if config file has changed and reload.
        
        Returns:
            True if config was reloaded
        """
        if not self._config_path:
            return False
        
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_reload_ms < self._reload_interval_ms:
            return False
        
        self._last_reload_ms = now_ms
        
        try:
            path = Path(self._config_path)
            if not path.exists():
                return False
            
            # Read and compare
            with open(path, "r") as f:
                new_data = json.load(f)
            
            current = self.to_dict()
            if new_data != current:
                # Reload
                reloaded = self.from_json(json.dumps(new_data))
                self.base_url = reloaded.base_url
                self.api_key = reloaded.api_key
                self.event_poll_interval_seconds = reloaded.event_poll_interval_seconds
                self.heartbeat_fallback_seconds = reloaded.heartbeat_fallback_seconds
                self.inbox_limit = reloaded.inbox_limit
                self.claim_ttl_seconds = reloaded.claim_ttl_seconds
                self.backlog_ceiling = reloaded.backlog_ceiling
                self.watched_channel_ids = reloaded.watched_channel_ids
                self.agent_handles = reloaded.agent_handles
                self.agent_user_ids = reloaded.agent_user_ids
                self.require_direct_address = reloaded.require_direct_address
                return True
        except Exception:
            pass
        
        return False

    def set_reload_interval(self, interval_ms: int) -> None:
        """Set the config reload check interval."""
        self._reload_interval_ms = max(1000, interval_ms)  # Minimum 1 second
