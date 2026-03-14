"""
CanopyKit Claim Worker - Claim/Timeout/Completion Structures

Handles mention claim lifecycle: claim acquisition, timeout management,
and completion tracking for the CanopyKit runtime.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timezone, timedelta


class ClaimStatus(Enum):
    """Lifecycle states for a claim."""
    PENDING = "pending"
    CLAIMED = "claimed"
    ACTIVE = "active"
    COMPLETED = "completed"
    RELEASED = "released"
    EXPIRED = "expired"
    FAILED = "failed"


class ClaimResult(Enum):
    """Result of claim completion."""
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ERROR = "error"
    CANCELLED = "cancelled"
    HANDLED_ELSEWHERE = "handled_elsewhere"


@dataclass
class ClaimConfig:
    """Configuration for claim behavior."""
    claim_timeout_seconds: int = 120  # Default claim lock duration
    max_retries: int = 3
    retry_delay_ms: int = 200
    heartbeat_interval_ms: int = 30000
    release_on_error: bool = True


@dataclass
class Claim:
    """
    Represents an acquired claim on a mention or work item.
    
    Claims are time-limited locks that prevent duplicate work across
    multiple agents. A claim must be either completed or released.
    """
    id: str
    source_id: str
    source_type: str
    channel_id: Optional[str] = None
    status: ClaimStatus = ClaimStatus.PENDING
    claimed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[ClaimResult] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.status == ClaimStatus.CLAIMED:
            if self.claimed_at is None:
                self.claimed_at = datetime.now(timezone.utc)
    
    @property
    def is_expired(self) -> bool:
        """Check if claim has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at
    
    @property
    def is_active(self) -> bool:
        """Check if claim is still valid for work."""
        return self.status == ClaimStatus.ACTIVE and not self.is_expired
    
    def remaining_seconds(self) -> Optional[int]:
        """Get remaining time before expiration."""
        if self.expires_at is None:
            return None
        remaining = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))


class ClaimTimeout:
    """
    Manages claim timeout tracking and extension.
    
    Provides:
    - Deadline tracking with remaining time queries
    - Extension capability for long-running operations
    - Timeout callback registration
    """
    
    def __init__(self, claim: Claim, config: ClaimConfig):
        self.claim = claim
        self.config = config
        self._extensions: list[int] = []
        self._timeout_callbacks: list[Callable[[Claim], None]] = []
    
    def start(self) -> None:
        """Initialize timeout countdown."""
        self.claim.status = ClaimStatus.ACTIVE
        self.claim.claimed_at = datetime.now(timezone.utc)
        self._set_expiry()
    
    def _set_expiry(self) -> None:
        """Set expiration time based on config and extensions."""
        base_timeout = self.config.claim_timeout_seconds
        extra_time = sum(self._extensions)
        self.claim.expires_at = datetime.now(
            timezone.utc
        ) + timedelta(seconds=base_timeout + extra_time)
    
    def extend(self, additional_seconds: int) -> bool:
        """
        Extend claim deadline.
        
        Args:
            additional_seconds: Time to add to deadline
            
        Returns:
            True if extension successful, False if claim invalid
        """
        if not self.claim.is_active:
            return False
        self._extensions.append(additional_seconds)
        self._set_expiry()
        self.claim.metadata["extensions"] = self._extensions.copy()
        return True
    
    def remaining_ms(self) -> int:
        """Get remaining time in milliseconds."""
        remaining = self.claim.remaining_seconds()
        if remaining is None:
            return self.config.claim_timeout_seconds * 1000
        return remaining * 1000
    
    def check_timeout(self) -> bool:
        """
        Check if claim has timed out.
        
        Returns:
            True if timed out, triggers callbacks if so
        """
        if self.claim.is_expired:
            self.claim.status = ClaimStatus.EXPIRED
            self.claim.result = ClaimResult.TIMEOUT
            self._run_timeout_callbacks()
            return True
        return False
    
    def on_timeout(self, callback: Callable[[Claim], None]) -> None:
        """Register callback for timeout event."""
        self._timeout_callbacks.append(callback)
    
    def _run_timeout_callbacks(self) -> None:
        """Execute all registered timeout callbacks."""
        for callback in self._timeout_callbacks:
            try:
                callback(self.claim)
            except Exception:
                pass  # Don't fail on callback errors


class CompletionTracker:
    """
    Tracks completion status and results for claim work.
    
    Provides:
    - Result recording with optional artifact references
    - Duration tracking
    - Error handling and failure states
    - Completion metadata storage
    """
    
    def __init__(self, claim: Claim):
        self.claim = claim
        self._artifacts: list[Dict[str, Any]] = []
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None
    
    def start_work(self) -> None:
        """Mark work as started."""
        self._start_time = time.time()
        self.claim.status = ClaimStatus.ACTIVE
    
    def complete(self, result: ClaimResult = ClaimResult.SUCCESS,
                 message: Optional[str] = None) -> Claim:
        """
        Mark claim as completed successfully.
        
        Args:
            result: Completion result type
            message: Optional completion message
            
        Returns:
            Updated claim
        """
        self._end_time = time.time()
        self.claim.status = ClaimStatus.COMPLETED
        self.claim.result = result
        self.claim.completed_at = datetime.now(timezone.utc)
        if message:
            self.claim.metadata["completion_message"] = message
        if self._start_time and self._end_time:
            self.claim.metadata["duration_seconds"] = round(
                self._end_time - self._start_time, 3
            )
        return self.claim
    
    def fail(self, error: str, exception: Optional[Exception] = None) -> Claim:
        """
        Mark claim as failed.
        
        Args:
            error: Error description
            exception: Optional exception that caused failure
            
        Returns:
            Updated claim
        """
        self._end_time = time.time()
        self.claim.status = ClaimStatus.FAILED
        self.claim.result = ClaimResult.ERROR
        self.claim.error_message = error
        self.claim.metadata["completion_message"] = error
        if exception:
            self.claim.metadata["exception_type"] = type(exception).__name__
        if self._start_time and self._end_time:
            self.claim.metadata["duration_seconds"] = round(
                self._end_time - self._start_time, 3
            )
        return self.claim
    
    def add_artifact(self, artifact_type: str, 
                     artifact_id: str,
                     artifact_url: Optional[str] = None) -> None:
        """
        Record an artifact produced by this claim's work.
        
        Args:
            artifact_type: Type of artifact (e.g., "message", "file", "pr")
            artifact_id: Unique identifier for artifact
            artifact_url: Optional URL reference
        """
        artifact = {
            "type": artifact_type,
            "id": artifact_id,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        if artifact_url:
            artifact["url"] = artifact_url
        self._artifacts.append(artifact)
        self.claim.metadata["artifacts"] = self._artifacts
    
    def get_artifacts(self) -> list[Dict[str, Any]]:
        """Get all recorded artifacts."""
        return self._artifacts.copy()
    
    def duration_ms(self) -> Optional[int]:
        """Get total work duration in milliseconds."""
        if self._start_time is None:
            return None
        end = self._end_time or time.time()
        return int((end - self._start_time) * 1000)


class ClaimWorker:
    """
    Main worker for claim lifecycle management.
    
    Coordinates:
    - Claim acquisition with retry logic
    - Timeout management with extensions
    - Completion tracking and reporting
    - Error handling and recovery
    """
    
    def __init__(self, config: Optional[ClaimConfig] = None):
        self.config = config or ClaimConfig()
        self._active_claims: Dict[str, Claim] = {}
        self._timeouts: Dict[str, ClaimTimeout] = {}
        self._completions: Dict[str, CompletionTracker] = {}
    
    def acquire(self, source_id: str, source_type: str,
                channel_id: Optional[str] = None,
                metadata: Optional[Dict[str, Any]] = None) -> Claim:
        """
        Acquire a new claim on a work item.
        
        Args:
            source_id: ID of the source (message, task, etc.)
            source_type: Type of source
            channel_id: Optional channel context
            metadata: Optional additional metadata
            
        Returns:
            Acquired claim ready for work
        """
        claim = Claim(
            id=f"CL{source_id[:16]}",
            source_id=source_id,
            source_type=source_type,
            channel_id=channel_id,
            status=ClaimStatus.CLAIMED,
            metadata=metadata or {}
        )
        
        timeout = ClaimTimeout(claim, self.config)
        completion = CompletionTracker(claim)
        
        timeout.start()
        
        self._active_claims[claim.id] = claim
        self._timeouts[claim.id] = timeout
        self._completions[claim.id] = completion
        
        return claim
    
    def get_claim(self, claim_id: str) -> Optional[Claim]:
        """Get claim by ID."""
        return self._active_claims.get(claim_id)
    
    def get_timeout(self, claim_id: str) -> Optional[ClaimTimeout]:
        """Get timeout manager for claim."""
        return self._timeouts.get(claim_id)
    
    def get_completion(self, claim_id: str) -> Optional[CompletionTracker]:
        """Get completion tracker for claim."""
        return self._completions.get(claim_id)
    
    def extend(self, claim_id: str, additional_seconds: int) -> bool:
        """
        Extend a claim's timeout.
        
        Args:
            claim_id: Claim to extend
            additional_seconds: Time to add
            
        Returns:
            True if extended, False if invalid
        """
        timeout = self._timeouts.get(claim_id)
        if timeout:
            return timeout.extend(additional_seconds)
        return False
    
    def complete(self, claim_id: str, result: ClaimResult = ClaimResult.SUCCESS,
                 message: Optional[str] = None) -> Optional[Claim]:
        """
        Mark a claim as completed.
        
        Args:
            claim_id: Claim to complete
            result: Completion result
            message: Optional message
            
        Returns:
            Completed claim or None if not found
        """
        completion = self._completions.get(claim_id)
        if completion:
            return completion.complete(result, message)
        return None
    
    def fail(self, claim_id: str, error: str) -> Optional[Claim]:
        """
        Mark a claim as failed.
        
        Args:
            claim_id: Claim to fail
            error: Error description
            
        Returns:
            Failed claim or None if not found
        """
        completion = self._completions.get(claim_id)
        if completion:
            return completion.fail(error)
        return None
    
    def release(self, claim_id: str) -> bool:
        """
        Release a claim without completion.
        
        Args:
            claim_id: Claim to release
            
        Returns:
            True if released, False if not found
        """
        claim = self._active_claims.get(claim_id)
        if claim:
            claim.status = ClaimStatus.RELEASED
            claim.result = ClaimResult.CANCELLED
            return True
        return False
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired claims from tracking.
        
        Returns:
            Number of claims cleaned up
        """
        expired = []
        for claim_id, claim in self._active_claims.items():
            if claim.is_expired:
                expired.append(claim_id)
        
        for claim_id in expired:
            self._timeouts.pop(claim_id, None)
            self._completions.pop(claim_id, None)
            self._active_claims.pop(claim_id, None)
        
        return len(expired)
    
    def active_count(self) -> int:
        """Count of currently active claims."""
        return sum(1 for c in self._active_claims.values() if c.is_active)
    
    def status_summary(self) -> Dict[str, int]:
        """Get summary of claims by status."""
        summary = {status.value: 0 for status in ClaimStatus}
        for claim in self._active_claims.values():
            summary[claim.status.value] += 1
        return summary


# Convenience exports
__all__ = [
    "ClaimStatus",
    "ClaimResult",
    "ClaimConfig",
    "Claim",
    "ClaimTimeout",
    "CompletionTracker",
    "ClaimWorker",
]
