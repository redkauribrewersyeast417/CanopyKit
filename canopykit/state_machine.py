"""
CanopyKit State Machine - Runtime State Transitions and Execution

Provides state-machine vocabulary, transition rules, and execution loop
for the CanopyKit runtime with timeout takeover and completion tracking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, Callable, Mapping


class RuntimeState(str, Enum):
    """Lifecycle states for the CanopyKit runtime."""
    IDLE = "idle"
    WAKING = "waking"
    FETCHING_EVENTS = "fetching_events"
    FETCHING_INBOX = "fetching_inbox"
    MARKING_SEEN = "marking_seen"
    CLAIMING = "claiming"
    EXECUTING = "executing"
    COMPLETING = "completing"
    SKIPPING = "skipping"
    TIMEOUT_TAKEOVER = "timeout_takeover"
    BACKING_OFF = "backing_off"
    RECOVERING = "recovering"
    ERROR = "error"


class TransitionTrigger(str, Enum):
    """Triggers that drive state transitions."""
    EVENT_ARRIVED = "event_arrived"
    CURSOR_READY = "cursor_ready"
    WORK_DETECTED = "work_detected"
    ITEM_SELECTED = "item_selected"
    CLAIM_REQUIRED = "claim_required"
    CLAIM_GRANTED = "claim_granted"
    ARTIFACT_READY = "artifact_ready"
    SKIP_DECISION = "skip_decision"
    CLAIM_EXPIRED = "claim_expired"
    TAKEOVER_GRANTED = "takeover_granted"
    COMPLETION_RECORDED = "completion_recorded"
    SKIP_RECORDED = "skip_recorded"
    ERROR_OCCURRED = "error_occurred"
    BACKOFF_COMPLETE = "backoff_complete"
    NO_WORK = "no_work"


@dataclass(slots=True)
class TransitionRule:
    """Defines a valid state transition."""
    from_state: RuntimeState
    to_state: RuntimeState
    trigger: str
    notes: str = ""


@dataclass
class StateContext:
    """
    Execution context carried through state transitions.
    
    Holds all runtime state needed for transition decisions,
    claim management, and completion tracking.
    """
    current_state: RuntimeState = RuntimeState.IDLE
    inbox_item_id: Optional[str] = None
    claim_id: Optional[str] = None
    claim_expires_at: Optional[float] = None
    completion_ref: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    backoff_until: Optional[float] = None
    artifacts: list[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Subscription status: active, authorization_rejected, downgraded, not_subscribed
    subscription_status: str = "not_subscribed"
    subscription_denied_reasons: tuple[str, ...] = ()
    
    def is_claim_expired(self) -> bool:
        """Check if current claim has expired."""
        if self.claim_expires_at is None:
            return False
        return time.time() >= self.claim_expires_at
    
    def remaining_claim_seconds(self) -> Optional[float]:
        """Get remaining claim time in seconds."""
        if self.claim_expires_at is None:
            return None
        return max(0.0, self.claim_expires_at - time.time())
    
    def add_artifact(self, artifact_type: str, artifact_id: str,
                     artifact_url: Optional[str] = None) -> None:
        """Record an artifact produced during execution."""
        artifact = {
            "type": artifact_type,
            "id": artifact_id,
            "created_at": time.time(),
        }
        if artifact_url:
            artifact["url"] = artifact_url
        self.artifacts.append(artifact)


# Default transition rules defining valid state machine paths
DEFAULT_TRANSITIONS: tuple[TransitionRule, ...] = (
    # Wake cycle
    TransitionRule(RuntimeState.IDLE, RuntimeState.WAKING, 
                   TransitionTrigger.EVENT_ARRIVED, "Wake on actionable event"),
    TransitionRule(RuntimeState.WAKING, RuntimeState.FETCHING_EVENTS, 
                   TransitionTrigger.CURSOR_READY, "Read agent event feed"),
    
    # Work detection cycle
    TransitionRule(RuntimeState.FETCHING_EVENTS, RuntimeState.FETCHING_INBOX, 
                   TransitionTrigger.WORK_DETECTED, "Fetch inbox when work detected"),
    TransitionRule(RuntimeState.FETCHING_EVENTS, RuntimeState.IDLE, 
                   TransitionTrigger.NO_WORK, "No work, return to idle"),
    
    # Inbox processing
    TransitionRule(RuntimeState.FETCHING_INBOX, RuntimeState.MARKING_SEEN, 
                   TransitionTrigger.ITEM_SELECTED, "Mark concrete item as seen"),
    TransitionRule(RuntimeState.MARKING_SEEN, RuntimeState.CLAIMING, 
                   TransitionTrigger.CLAIM_REQUIRED, "Claim mention-backed work"),
    
    # Claim and execution
    TransitionRule(RuntimeState.CLAIMING, RuntimeState.EXECUTING, 
                   TransitionTrigger.CLAIM_GRANTED, "Proceed with owned work"),
    TransitionRule(RuntimeState.CLAIMING, RuntimeState.TIMEOUT_TAKEOVER, 
                   TransitionTrigger.CLAIM_EXPIRED, "Take over timed-out work"),
    TransitionRule(RuntimeState.TIMEOUT_TAKEOVER, RuntimeState.EXECUTING, 
                   TransitionTrigger.TAKEOVER_GRANTED, "Continue under same claim record"),
    
    # Completion paths
    TransitionRule(RuntimeState.EXECUTING, RuntimeState.COMPLETING, 
                   TransitionTrigger.ARTIFACT_READY, "Complete with evidence"),
    TransitionRule(RuntimeState.COMPLETING, RuntimeState.IDLE, 
                   TransitionTrigger.COMPLETION_RECORDED, "Return to idle after completion"),
    
    # Skip path (no work needed)
    TransitionRule(RuntimeState.EXECUTING, RuntimeState.SKIPPING, 
                   TransitionTrigger.SKIP_DECISION, "Skip with reason/evidence"),
    TransitionRule(RuntimeState.SKIPPING, RuntimeState.IDLE, 
                   TransitionTrigger.SKIP_RECORDED, "Return to idle after skip"),
    
    # Error handling
    TransitionRule(RuntimeState.EXECUTING, RuntimeState.ERROR, 
                   TransitionTrigger.ERROR_OCCURRED, "Error during execution"),
    TransitionRule(RuntimeState.ERROR, RuntimeState.BACKING_OFF, 
                   TransitionTrigger.BACKOFF_COMPLETE, "Backoff after error"),
    TransitionRule(RuntimeState.BACKING_OFF, RuntimeState.IDLE, 
                   TransitionTrigger.BACKOFF_COMPLETE, "Return to idle after backoff"),
    
    # Recovery path
    TransitionRule(RuntimeState.ERROR, RuntimeState.RECOVERING, 
                   TransitionTrigger.TAKEOVER_GRANTED, "Begin recovery after error"),
    TransitionRule(RuntimeState.TIMEOUT_TAKEOVER, RuntimeState.RECOVERING,
                   TransitionTrigger.TAKEOVER_GRANTED, "Recovery from takeover"),
    TransitionRule(RuntimeState.RECOVERING, RuntimeState.FETCHING_EVENTS,
                   TransitionTrigger.CURSOR_READY, "Resume after recovery"),
)


def build_transition_map() -> Mapping[RuntimeState, tuple[TransitionRule, ...]]:
    """
    Build a lookup map of valid transitions from each state.
    
    Returns:
        Mapping from state to valid transition rules
    """
    out: Dict[RuntimeState, list[TransitionRule]] = {}
    for rule in DEFAULT_TRANSITIONS:
        out.setdefault(rule.from_state, []).append(rule)
    return {key: tuple(value) for key, value in out.items()}


class StateMachine:
    """
    State machine executor for CanopyKit runtime.
    
    Manages state transitions, claim lifecycle, timeout takeover,
    and completion tracking with evidence.
    """
    
    def __init__(self, transitions: Optional[tuple[TransitionRule, ...]] = None):
        self.transitions = transitions or DEFAULT_TRANSITIONS
        self._transition_map = build_transition_map()
        self._context = StateContext()
        self._step_handlers: Dict[RuntimeState, Callable[[StateContext], str]] = {}
    
    @property
    def context(self) -> StateContext:
        """Current execution context."""
        return self._context
    
    @property
    def current_state(self) -> RuntimeState:
        """Current state machine state."""
        return self._context.current_state
    
    def register_handler(self, state: RuntimeState, 
                         handler: Callable[[StateContext], str]) -> None:
        """
        Register a handler for a specific state.
        
        Args:
            state: State to handle
            handler: Function that takes context and returns trigger
        """
        self._step_handlers[state] = handler
    
    def valid_triggers(self) -> tuple[str, ...]:
        """Get valid triggers from current state."""
        rules = self._transition_map.get(self.current_state, ())
        return tuple(rule.trigger for rule in rules)
    
    def can_transition(self, trigger: str) -> bool:
        """
        Check if transition is valid from current state.
        
        Args:
            trigger: Trigger to check
            
        Returns:
            True if transition is valid
        """
        return trigger in self.valid_triggers()
    
    def transition(self, trigger: str) -> bool:
        """
        Execute a state transition.
        
        Args:
            trigger: Trigger for transition
            
        Returns:
            True if transition succeeded
        """
        if not self.can_transition(trigger):
            return False
        
        rules = self._transition_map.get(self.current_state, ())
        for rule in rules:
            if rule.trigger == trigger:
                self._context.current_state = rule.to_state
                self._context.metadata["last_transition"] = {
                    "from": rule.from_state.value,
                    "to": rule.to_state.value,
                    "trigger": trigger,
                    "timestamp": time.time(),
                }
                return True
        
        return False
    
    def step(self) -> Optional[str]:
        """
        Execute one state machine step.
        
        Runs the registered handler for current state and
        attempts to transition based on returned trigger.
        
        Returns:
            Trigger that was executed, or None if no handler
        """
        handler = self._step_handlers.get(self.current_state)
        if handler is None:
            return None
        
        trigger = handler(self._context)
        if trigger and self.transition(trigger):
            return trigger
        
        return None
    
    def run_until_idle(self, max_steps: int = 100) -> tuple[bool, int]:
        """
        Run state machine until it returns to IDLE state.
        
        Args:
            max_steps: Maximum steps before stopping
            
        Returns:
            Tuple of (completed, steps_taken)
        """
        steps = 0
        while self.current_state != RuntimeState.IDLE and steps < max_steps:
            trigger = self.step()
            if trigger is None:
                # No handler registered, cannot continue
                break
            steps += 1
        
        return (self.current_state == RuntimeState.IDLE, steps)
    
    def start_claim(self, claim_id: str, claim_id_timeout_seconds: float,
                    inbox_item_id: Optional[str] = None) -> None:
        """
        Initialize claim tracking in context.
        
        Args:
            claim_id: Unique claim identifier
            claim_id_timeout_seconds: Time until claim expires
            inbox_item_id: Optional inbox item being claimed
        """
        self._context.claim_id = claim_id
        self._context.claim_expires_at = time.time() + claim_id_timeout_seconds
        self._context.inbox_item_id = inbox_item_id
    
    def takeover_expired_claim(self, new_claim_id: str) -> bool:
        """
        Take over an expired claim.
        
        Validates that current claim is expired and creates
        new claim context while preserving execution state.
        
        Args:
            new_claim_id: New claim identifier for takeover
            
        Returns:
            True if takeover succeeded
        """
        if not self._context.is_claim_expired():
            return False
        
        if self.current_state != RuntimeState.TIMEOUT_TAKEOVER:
            return False
        
        # Preserve execution context, update claim
        old_claim_id = self._context.claim_id
        self._context.claim_id = new_claim_id
        self._context.claim_expires_at = time.time() + 120  # Default 2 min extension
        self._context.metadata["takeover"] = {
            "original_claim": old_claim_id,
            "new_claim": new_claim_id,
            "timestamp": time.time(),
        }
        
        return True
    
    def complete(self, completion_ref: Dict[str, Any]) -> bool:
        """
        Mark execution as complete with evidence.
        
        Args:
            completion_ref: Completion evidence reference
            
        Returns:
            True if in COMPLETING state and successful
        """
        if self.current_state != RuntimeState.COMPLETING:
            return False
        
        # completion_ref is required for terminal success states
        if not completion_ref:
            return False
        
        self._context.completion_ref = completion_ref
        self._context.metadata["completed_at"] = time.time()
        
        return self.transition(TransitionTrigger.COMPLETION_RECORDED)
    
    def skip(self, reason: str) -> bool:
        """
        Mark execution as skipped with reason.
        
        Args:
            reason: Reason for skipping
            
        Returns:
            True if in SKIPPING state and successful
        """
        if self.current_state != RuntimeState.SKIPPING:
            return False
        
        self._context.metadata["skip_reason"] = reason
        self._context.metadata["skipped_at"] = time.time()
        
        return self.transition(TransitionTrigger.SKIP_RECORDED)
    
    def error(self, message: str) -> bool:
        """
        Record an error and transition to ERROR state.
        
        Args:
            message: Error message
            
        Returns:
            True if transition succeeded
        """
        self._context.error_message = message
        self._context.metadata["error_at"] = time.time()
        
        if self.transition(TransitionTrigger.ERROR_OCCURRED):
            return True
        
        # Force to ERROR state if transition fails
        self._context.current_state = RuntimeState.ERROR
        return True
    
    def reset(self) -> None:
        """Reset state machine to initial IDLE state with fresh context."""
        self._context = StateContext()

    def begin_recovery(self, reason: str = "error_recovery") -> bool:
        """
        Begin recovery from error or timeout state.
        
        Args:
            reason: Reason for recovery
            
        Returns:
            True if recovery transition succeeded
        """
        if self.current_state not in (RuntimeState.ERROR, RuntimeState.TIMEOUT_TAKEOVER):
            return False
        
        self._context.metadata["recovery_reason"] = reason
        self._context.metadata["recovery_started_at"] = time.time()
        
        return self.transition(TransitionTrigger.TAKEOVER_GRANTED)
    
    def is_recoverable(self) -> bool:
        """
        Check if current state allows recovery.
        
        Returns:
            True if can transition to RECOVERING state
        """
        return self.current_state in (RuntimeState.ERROR, RuntimeState.TIMEOUT_TAKEOVER)
    
    def recovery_status(self) -> Dict[str, Any]:
        """
        Get current recovery status.
        
        Returns:
            Dict with recovery information if in RECOVERING state
        """
        if self.current_state != RuntimeState.RECOVERING:
            return {"in_recovery": False}
        
        return {
            "in_recovery": True,
            "reason": self._context.metadata.get("recovery_reason", "unknown"),
            "started_at": self._context.metadata.get("recovery_started_at"),
            "claim_id": self._context.claim_id,
            "artifacts_count": len(self._context.artifacts),
        }


def execute_step(context: StateContext, 
                 handlers: Optional[Dict[RuntimeState, Callable[[StateContext], str]]] = None) -> str:
    """
    Execute a single state machine step.
    
    Utility function for manual step-by-step execution.
    
    Args:
        context: Current execution context
        handlers: Optional state-to-handler mapping
        
    Returns:
        Trigger that was executed or empty string
    """
    state = context.current_state
    
    if state == RuntimeState.IDLE:
        return TransitionTrigger.NO_WORK
    
    # Default step logic based on state
    if state == RuntimeState.FETCHING_EVENTS:
        return TransitionTrigger.WORK_DETECTED
    elif state == RuntimeState.FETCHING_INBOX:
        return TransitionTrigger.ITEM_SELECTED
    elif state == RuntimeState.MARKING_SEEN:
        return TransitionTrigger.CLAIM_REQUIRED
    elif state == RuntimeState.CLAIMING:
        if context.is_claim_expired():
            return TransitionTrigger.CLAIM_EXPIRED
        return TransitionTrigger.CLAIM_GRANTED
    elif state == RuntimeState.EXECUTING:
        if context.artifacts:
            return TransitionTrigger.ARTIFACT_READY
        return TransitionTrigger.SKIP_DECISION
    elif state == RuntimeState.COMPLETING:
        return TransitionTrigger.COMPLETION_RECORDED
    elif state == RuntimeState.SKIPPING:
        return TransitionTrigger.SKIP_RECORDED
    elif state == RuntimeState.TIMEOUT_TAKEOVER:
        return TransitionTrigger.TAKEOVER_GRANTED
    elif state == RuntimeState.ERROR:
        return TransitionTrigger.BACKOFF_COMPLETE
    elif state == RuntimeState.RECOVERING:
        return TransitionTrigger.CURSOR_READY
    
    return ""


# Convenience exports
__all__ = [
    "RuntimeState",
    "TransitionTrigger",
    "TransitionRule",
    "StateContext",
    "DEFAULT_TRANSITIONS",
    "build_transition_map",
    "StateMachine",
    "execute_step",
]