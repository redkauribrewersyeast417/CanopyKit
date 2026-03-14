"""Tests for canopykit/state_machine.py - Runtime state machine."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from canopykit.state_machine import (
    RuntimeState,
    TransitionTrigger,
    TransitionRule,
    StateContext,
    DEFAULT_TRANSITIONS,
    build_transition_map,
    StateMachine,
    execute_step,
)


class TestRuntimeState:
    """Test RuntimeState enum values."""

    def test_state_values_exist(self):
        """All expected state values are defined."""
        assert RuntimeState.IDLE.value == "idle"
        assert RuntimeState.WAKING.value == "waking"
        assert RuntimeState.FETCHING_EVENTS.value == "fetching_events"
        assert RuntimeState.FETCHING_INBOX.value == "fetching_inbox"
        assert RuntimeState.MARKING_SEEN.value == "marking_seen"
        assert RuntimeState.CLAIMING.value == "claiming"
        assert RuntimeState.EXECUTING.value == "executing"
        assert RuntimeState.COMPLETING.value == "completing"
        assert RuntimeState.SKIPPING.value == "skipping"
        assert RuntimeState.TIMEOUT_TAKEOVER.value == "timeout_takeover"
        assert RuntimeState.BACKING_OFF.value == "backing_off"
        assert RuntimeState.ERROR.value == "error"


class TestTransitionTrigger:
    """Test TransitionTrigger enum values."""

    def test_trigger_values_exist(self):
        """All expected trigger values are defined."""
        assert TransitionTrigger.EVENT_ARRIVED.value == "event_arrived"
        assert TransitionTrigger.CURSOR_READY.value == "cursor_ready"
        assert TransitionTrigger.WORK_DETECTED.value == "work_detected"
        assert TransitionTrigger.ITEM_SELECTED.value == "item_selected"
        assert TransitionTrigger.CLAIM_REQUIRED.value == "claim_required"
        assert TransitionTrigger.CLAIM_GRANTED.value == "claim_granted"
        assert TransitionTrigger.ARTIFACT_READY.value == "artifact_ready"
        assert TransitionTrigger.CLAIM_EXPIRED.value == "claim_expired"
        assert TransitionTrigger.COMPLETION_RECORDED.value == "completion_recorded"


class TestTransitionRule:
    """Test TransitionRule dataclass."""

    def test_rule_creation(self):
        """Rule is created with expected fields."""
        rule = TransitionRule(
            from_state=RuntimeState.IDLE,
            to_state=RuntimeState.WAKING,
            trigger=TransitionTrigger.EVENT_ARRIVED,
            notes="Wake on event",
        )
        assert rule.from_state == RuntimeState.IDLE
        assert rule.to_state == RuntimeState.WAKING
        assert rule.trigger == TransitionTrigger.EVENT_ARRIVED
        assert rule.notes == "Wake on event"

    def test_rule_default_notes(self):
        """Notes default to empty string."""
        rule = TransitionRule(
            from_state=RuntimeState.IDLE,
            to_state=RuntimeState.WAKING,
            trigger=TransitionTrigger.EVENT_ARRIVED,
        )
        assert rule.notes == ""


class TestStateContext:
    """Test StateContext dataclass."""

    def test_context_creation(self):
        """Context is created with default values."""
        context = StateContext()
        assert context.current_state == RuntimeState.IDLE
        assert context.inbox_item_id is None
        assert context.claim_id is None
        assert context.claim_expires_at is None
        assert context.completion_ref is None
        assert context.error_message is None
        assert context.artifacts == []
        assert context.metadata == {}

    def test_is_claim_expired_false_when_no_claim(self):
        """Context without claim is not expired."""
        context = StateContext()
        assert context.is_claim_expired() is False

    def test_is_claim_expired_true_when_past(self):
        """Context with past expiry is expired."""
        context = StateContext(
            claim_expires_at=time.time() - 1  # Expired 1 second ago
        )
        assert context.is_claim_expired() is True

    def test_is_claim_expired_false_when_future(self):
        """Context with future expiry is not expired."""
        context = StateContext(
            claim_expires_at=time.time() + 60  # Expires in 60 seconds
        )
        assert context.is_claim_expired() is False

    def test_remaining_claim_seconds(self):
        """Remaining seconds calculation works."""
        context = StateContext(
            claim_expires_at=time.time() + 30
        )
        remaining = context.remaining_claim_seconds()
        assert remaining is not None
        assert 29 <= remaining <= 30  # Allow slight timing drift

    def test_add_artifact(self):
        """Artifact recording works."""
        context = StateContext()
        context.add_artifact("message", "M12345", "https://example.com/msg/12345")
        
        assert len(context.artifacts) == 1
        assert context.artifacts[0]["type"] == "message"
        assert context.artifacts[0]["id"] == "M12345"
        assert context.artifacts[0]["url"] == "https://example.com/msg/12345"
        assert "created_at" in context.artifacts[0]


class TestDefaultTransitions:
    """Test DEFAULT_TRANSITIONS tuple."""

    def test_transitions_exist(self):
        """Default transitions are defined."""
        assert len(DEFAULT_TRANSITIONS) > 0

    def test_idle_to_waking(self):
        """IDLE to WAKING transition exists."""
        found = False
        for rule in DEFAULT_TRANSITIONS:
            if rule.from_state == RuntimeState.IDLE and rule.to_state == RuntimeState.WAKING:
                found = True
                assert rule.trigger == TransitionTrigger.EVENT_ARRIVED
        assert found

    def test_timeout_takeover_path(self):
        """Timeout takeover path exists."""
        takeover_rule = None
        for rule in DEFAULT_TRANSITIONS:
            if rule.from_state == RuntimeState.CLAIMING and rule.to_state == RuntimeState.TIMEOUT_TAKEOVER:
                takeover_rule = rule
                break
        
        assert takeover_rule is not None
        assert takeover_rule.trigger == TransitionTrigger.CLAIM_EXPIRED

        # Check continuation from TIMEOUT_TAKEOVER
        continue_rule = None
        for rule in DEFAULT_TRANSITIONS:
            if rule.from_state == RuntimeState.TIMEOUT_TAKEOVER and rule.to_state == RuntimeState.EXECUTING:
                continue_rule = rule
                break
        
        assert continue_rule is not None


class TestBuildTransitionMap:
    """Test build_transition_map function."""

    def test_map_builds(self):
        """Transition map builds correctly."""
        trans_map = build_transition_map()
        
        # IDLE should have transitions
        assert RuntimeState.IDLE in trans_map
        assert len(trans_map[RuntimeState.IDLE]) >= 1

    def test_map_contains_all_states(self):
        """Map contains transitions for all source states."""
        trans_map = build_transition_map()
        
        source_states = set(rule.from_state for rule in DEFAULT_TRANSITIONS)
        for state in source_states:
            assert state in trans_map


class TestStateMachine:
    """Test StateMachine class."""

    def test_machine_creation(self):
        """Machine is created with default state."""
        sm = StateMachine()
        assert sm.current_state == RuntimeState.IDLE
        assert sm.context is not None

    def test_valid_triggers(self):
        """Valid triggers returns expected triggers."""
        sm = StateMachine()
        # IDLE state should have EVENT_ARRIVED as valid trigger
        triggers = sm.valid_triggers()
        assert TransitionTrigger.EVENT_ARRIVED in triggers

    def test_can_transition(self):
        """Can check valid transitions."""
        sm = StateMachine()
        assert sm.can_transition(TransitionTrigger.EVENT_ARRIVED) is True
        assert sm.can_transition(TransitionTrigger.ARTIFACT_READY) is False

    def test_transition_succeeds(self):
        """Valid transition succeeds."""
        sm = StateMachine()
        result = sm.transition(TransitionTrigger.EVENT_ARRIVED)
        assert result is True
        assert sm.current_state == RuntimeState.WAKING

    def test_transition_fails_for_invalid(self):
        """Invalid transition fails."""
        sm = StateMachine()
        result = sm.transition(TransitionTrigger.ARTIFACT_READY)
        assert result is False
        assert sm.current_state == RuntimeState.IDLE

    def test_register_handler(self):
        """Handler registration works."""
        sm = StateMachine()
        
        def wake_handler(ctx: StateContext) -> str:
            return TransitionTrigger.CURSOR_READY
        
        sm.register_handler(RuntimeState.WAKING, wake_handler)
        sm.transition(TransitionTrigger.EVENT_ARRIVED)  # Move to WAKING
        
        trigger = sm.step()
        assert trigger == TransitionTrigger.CURSOR_READY
        assert sm.current_state == RuntimeState.FETCHING_EVENTS

    def test_step_returns_none_without_handler(self):
        """Step returns None when no handler registered."""
        sm = StateMachine()
        trigger = sm.step()
        assert trigger is None

    def test_run_until_idle(self):
        """run_until_idle executes until IDLE."""
        sm = StateMachine()
        
        # Register minimal handlers to reach IDLE
        sm.register_handler(RuntimeState.WAKING, lambda ctx: TransitionTrigger.CURSOR_READY)
        sm.register_handler(RuntimeState.FETCHING_EVENTS, lambda ctx: TransitionTrigger.NO_WORK)
        
        # Start from IDLE - should immediately return
        completed, steps = sm.run_until_idle()
        assert completed is True
        assert steps == 0

    def test_start_claim(self):
        """start_claim initializes claim tracking."""
        sm = StateMachine()
        sm.start_claim("CL12345", 120, "IN999")
        
        assert sm.context.claim_id == "CL12345"
        assert sm.context.inbox_item_id == "IN999"
        assert sm.context.claim_expires_at is not None

    def test_takeover_expired_claim_succeeds(self):
        """takeover_expired_claim works when expired."""
        sm = StateMachine()
        sm.start_claim("CL12345", -1)  # Already expired
        sm._context.current_state = RuntimeState.TIMEOUT_TAKEOVER
        
        result = sm.takeover_expired_claim("CL_NEW")
        assert result is True
        assert sm.context.claim_id == "CL_NEW"
        assert "takeover" in sm.context.metadata

    def test_takeover_expired_claim_fails_when_not_expired(self):
        """takeover_expired_claim fails when not expired."""
        sm = StateMachine()
        sm.start_claim("CL12345", 120)  # Not expired
        sm._context.current_state = RuntimeState.TIMEOUT_TAKEOVER
        
        result = sm.takeover_expired_claim("CL_NEW")
        assert result is False

    def test_complete_succeeds(self):
        """complete with completion_ref succeeds."""
        sm = StateMachine()
        sm._context.current_state = RuntimeState.COMPLETING
        
        result = sm.complete({"message_id": "M12345"})
        assert result is True
        assert sm.context.completion_ref == {"message_id": "M12345"}

    def test_complete_requires_completion_ref(self):
        """complete fails without completion_ref."""
        sm = StateMachine()
        sm._context.current_state = RuntimeState.COMPLETING
        
        result = sm.complete({})
        assert result is False

    def test_complete_fails_in_wrong_state(self):
        """complete fails when not in COMPLETING state."""
        sm = StateMachine()
        
        result = sm.complete({"message_id": "M12345"})
        assert result is False

    def test_skip_succeeds(self):
        """skip with reason succeeds."""
        sm = StateMachine()
        sm._context.current_state = RuntimeState.SKIPPING
        
        result = sm.skip("No work needed")
        assert result is True
        assert sm.context.metadata["skip_reason"] == "No work needed"

    def test_error_transitions(self):
        """error transitions to ERROR state."""
        sm = StateMachine()
        
        result = sm.error("Something went wrong")
        assert result is True
        assert sm.current_state == RuntimeState.ERROR
        assert sm.context.error_message == "Something went wrong"

    def test_reset(self):
        """reset restores initial state."""
        sm = StateMachine()
        sm.transition(TransitionTrigger.EVENT_ARRIVED)
        sm.context.claim_id = "CL12345"
        
        sm.reset()
        
        assert sm.current_state == RuntimeState.IDLE
        assert sm.context.claim_id is None


class TestExecuteStep:
    """Test execute_step utility function."""

    def test_idle_returns_no_work(self):
        """_IDLE state returns NO_WORK."""
        context = StateContext(current_state=RuntimeState.IDLE)
        trigger = execute_step(context)
        assert trigger == TransitionTrigger.NO_WORK

    def test_fetching_events_returns_work_detected(self):
        """FETCHING_EVENTS returns WORK_DETECTED."""
        context = StateContext(current_state=RuntimeState.FETCHING_EVENTS)
        trigger = execute_step(context)
        assert trigger == TransitionTrigger.WORK_DETECTED

    def test_claiming_returns_claim_expired_when_expired(self):
        """CLAIMING returns CLAIM_EXPIRED when expired."""
        context = StateContext(
            current_state=RuntimeState.CLAIMING,
            claim_expires_at=time.time() - 1,  # Expired
        )
        trigger = execute_step(context)
        assert trigger == TransitionTrigger.CLAIM_EXPIRED

    def test_claiming_returns_claim_granted_when_not_expired(self):
        """CLAIMING returns CLAIM_GRANTED when not expired."""
        context = StateContext(
            current_state=RuntimeState.CLAIMING,
            claim_expires_at=time.time() + 60,  # Not expired
        )
        trigger = execute_step(context)
        assert trigger == TransitionTrigger.CLAIM_GRANTED

    def test_executing_returns_artifact_ready_with_artifacts(self):
        """EXECUTING returns ARTIFACT_READY when artifacts exist."""
        context = StateContext(
            current_state=RuntimeState.EXECUTING,
            artifacts=[{"type": "message", "id": "M123"}],
        )
        trigger = execute_step(context)
        assert trigger == TransitionTrigger.ARTIFACT_READY

    def test_executing_returns_skip_decision_without_artifacts(self):
        """EXECUTING returns SKIP_DECISION when no artifacts."""
        context = StateContext(current_state=RuntimeState.EXECUTING)
        trigger = execute_step(context)
        assert trigger == TransitionTrigger.SKIP_DECISION