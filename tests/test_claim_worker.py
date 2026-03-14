"""Tests for canopykit/claim_worker.py - Claim lifecycle management."""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import pytest

from canopykit.claim_worker import (
    ClaimStatus,
    ClaimResult,
    ClaimConfig,
    Claim,
    ClaimTimeout,
    CompletionTracker,
    ClaimWorker,
)


class TestClaimStatus:
    """Test ClaimStatus enum values."""

    def test_status_values_exist(self):
        """All expected status values are defined."""
        assert ClaimStatus.PENDING.value == "pending"
        assert ClaimStatus.CLAIMED.value == "claimed"
        assert ClaimStatus.ACTIVE.value == "active"
        assert ClaimStatus.COMPLETED.value == "completed"
        assert ClaimStatus.RELEASED.value == "released"
        assert ClaimStatus.EXPIRED.value == "expired"
        assert ClaimStatus.FAILED.value == "failed"


class TestClaimResult:
    """Test ClaimResult enum values."""

    def test_result_values_exist(self):
        """All expected result values are defined."""
        assert ClaimResult.SUCCESS.value == "success"
        assert ClaimResult.TIMEOUT.value == "timeout"
        assert ClaimResult.ERROR.value == "error"
        assert ClaimResult.CANCELLED.value == "cancelled"
        assert ClaimResult.HANDLED_ELSEWHERE.value == "handled_elsewhere"


class TestClaimConfig:
    """Test ClaimConfig dataclass."""

    def test_default_config(self):
        """Default config has expected values."""
        config = ClaimConfig()
        assert config.claim_timeout_seconds == 120
        assert config.max_retries == 3
        assert config.retry_delay_ms == 200
        assert config.heartbeat_interval_ms == 30000
        assert config.release_on_error is True

    def test_custom_config(self):
        """Custom config values are applied."""
        config = ClaimConfig(
            claim_timeout_seconds=60,
            max_retries=5,
            release_on_error=False,
        )
        assert config.claim_timeout_seconds == 60
        assert config.max_retries == 5
        assert config.release_on_error is False


class TestClaim:
    """Test Claim dataclass."""

    def test_claim_creation(self):
        """Claim is created with expected fields."""
        claim = Claim(
            id="CL12345",
            source_id="M12345",
            source_type="mention",
        )
        assert claim.id == "CL12345"
        assert claim.source_id == "M12345"
        assert claim.source_type == "mention"
        assert claim.status == ClaimStatus.PENDING
        assert claim.metadata == {}

    def test_claim_with_channel(self):
        """Claim can include channel context."""
        claim = Claim(
            id="CL12345",
            source_id="M12345",
            source_type="mention",
            channel_id="C12345",
        )
        assert claim.channel_id == "C12345"

    def test_is_expired_false_when_no_expiry(self):
        """Claim without expiry is not expired."""
        claim = Claim(id="CL1", source_id="M1", source_type="mention")
        assert claim.is_expired is False

    def test_is_expired_true_when_past_expiry(self):
        """Claim past expiry time is expired."""
        claim = Claim(
            id="CL1",
            source_id="M1",
            source_type="mention",
            status=ClaimStatus.ACTIVE,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert claim.is_expired is True

    def test_is_active_when_claimed_and_not_expired(self):
        """Claim is active when claimed and not expired."""
        claim = Claim(
            id="CL1",
            source_id="M1",
            source_type="mention",
            status=ClaimStatus.ACTIVE,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
        assert claim.is_active is True

    def test_remaining_seconds(self):
        """remaining_seconds returns expected duration."""
        claim = Claim(
            id="CL1",
            source_id="M1",
            source_type="mention",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        remaining = claim.remaining_seconds()
        assert remaining is not None
        assert remaining >= 29  # Allow for slight timing drift


class TestClaimTimeout:
    """Test ClaimTimeout manager."""

    def test_timeout_starts_claim(self):
        """Starting timeout sets claim to active."""
        claim = Claim(id="CL1", source_id="M1", source_type="mention")
        config = ClaimConfig(claim_timeout_seconds=60)
        timeout = ClaimTimeout(claim, config)
        timeout.start()
        
        assert claim.status == ClaimStatus.ACTIVE
        assert claim.claimed_at is not None
        assert claim.expires_at is not None

    def test_timeout_sets_expiry(self):
        """Timeout sets correct expiry time."""
        claim = Claim(id="CL1", source_id="M1", source_type="mention")
        config = ClaimConfig(claim_timeout_seconds=120)
        timeout = ClaimTimeout(claim, config)
        timeout.start()
        
        # Expiry should be approximately 120 seconds from now
        assert claim.expires_at is not None
        expected_expiry = datetime.now(timezone.utc) + timedelta(seconds=120)
        delta = abs((claim.expires_at - expected_expiry).total_seconds())
        assert delta < 1  # Within 1 second tolerance

    def test_extend_timeout(self):
        """Extending timeout adds time."""
        claim = Claim(id="CL1", source_id="M1", source_type="mention")
        config = ClaimConfig(claim_timeout_seconds=60)
        timeout = ClaimTimeout(claim, config)
        timeout.start()
        
        # Extend by 30 seconds
        result = timeout.extend(30)
        assert result is True
        
        # Check extensions recorded
        assert "extensions" in claim.metadata
        assert claim.metadata["extensions"] == [30]

    def test_extend_fails_on_expired_claim(self):
        """Extending expired claim fails."""
        claim = Claim(
            id="CL1",
            source_id="M1",
            source_type="mention",
            status=ClaimStatus.EXPIRED,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        config = ClaimConfig()
        timeout = ClaimTimeout(claim, config)
        
        result = timeout.extend(30)
        assert result is False


class TestCompletionTracker:
    """Test CompletionTracker."""

    def test_complete_success(self):
        """Completing with success sets expected state."""
        claim = Claim(id="CL1", source_id="M1", source_type="mention")
        tracker = CompletionTracker(claim)
        tracker.start_work()
        
        result = tracker.complete(ClaimResult.SUCCESS, message="Done")
        
        assert result.status == ClaimStatus.COMPLETED
        assert result.result == ClaimResult.SUCCESS
        assert result.completed_at is not None
        assert result.metadata["completion_message"] == "Done"

    def test_complete_with_artifacts(self):
        """Completion can record artifacts."""
        claim = Claim(id="CL1", source_id="M1", source_type="mention")
        tracker = CompletionTracker(claim)
        tracker.start_work()
        
        tracker.add_artifact("message", "M12345", "https://example.com/msg/12345")
        tracker.add_artifact("file", "PR1")
        tracker.complete(ClaimResult.SUCCESS)
        
        artifacts = tracker.get_artifacts()
        assert len(artifacts) == 2
        assert artifacts[0]["type"] == "message"
        assert artifacts[0]["url"] == "https://example.com/msg/12345"

    def test_fail_sets_error_state(self):
        """Failing claim sets expected state."""
        claim = Claim(id="CL1", source_id="M1", source_type="mention")
        tracker = CompletionTracker(claim)
        tracker.start_work()
        
        result = tracker.fail("Connection timeout")
        
        assert result.status == ClaimStatus.FAILED
        assert result.result == ClaimResult.ERROR
        assert result.error_message == "Connection timeout"

    def test_duration_tracking(self):
        """Duration is tracked correctly."""
        claim = Claim(id="CL1", source_id="M1", source_type="mention")
        tracker = CompletionTracker(claim)
        
        tracker.start_work()
        time.sleep(0.1)  # 100ms
        tracker.complete(ClaimResult.SUCCESS)
        
        duration = tracker.duration_ms()
        assert duration is not None
        assert duration >= 100  # At least 100ms


class TestClaimWorker:
    """Test ClaimWorker orchestrator."""

    def test_acquire_claim(self):
        """Acquiring claim creates valid structure."""
        worker = ClaimWorker()
        claim = worker.acquire(
            source_id="M12345",
            source_type="mention",
            channel_id="C12345",
        )
        
        assert claim.id.startswith("CL")
        assert claim.source_id == "M12345"
        assert claim.source_type == "mention"
        assert claim.status == ClaimStatus.ACTIVE
        assert claim in worker._active_claims.values()

    def test_get_claim_by_id(self):
        """Can retrieve claim by ID."""
        worker = ClaimWorker()
        acquired = worker.acquire("M1", "mention")
        
        retrieved = worker.get_claim(acquired.id)
        assert retrieved is acquired

    def test_complete_claim(self):
        """Completing claim works through worker."""
        worker = ClaimWorker()
        claim = worker.acquire("M1", "mention")
        
        result = worker.complete(claim.id, ClaimResult.SUCCESS, "Done")
        
        assert result is not None
        assert result.status == ClaimStatus.COMPLETED
        assert result.result == ClaimResult.SUCCESS

    def test_fail_claim(self):
        """Failing claim works through worker."""
        worker = ClaimWorker()
        claim = worker.acquire("M1", "mention")
        
        result = worker.fail(claim.id, "Something went wrong")
        
        assert result is not None
        assert result.status == ClaimStatus.FAILED

    def test_release_claim(self):
        """Releasing claim works."""
        worker = ClaimWorker()
        claim = worker.acquire("M1", "mention")
        
        result = worker.release(claim.id)
        
        assert result is True
        retrieved = worker.get_claim(claim.id)
        assert retrieved.status == ClaimStatus.RELEASED
        assert retrieved.result == ClaimResult.CANCELLED

    def test_extend_claim(self):
        """Extending claim works through worker."""
        worker = ClaimWorker(ClaimConfig(claim_timeout_seconds=60))
        claim = worker.acquire("M1", "mention")
        
        result = worker.extend(claim.id, 30)
        
        assert result is True

    def test_cleanup_expired(self):
        """Cleanup removes expired claims."""
        worker = ClaimWorker()
        claim = worker.acquire("M1", "mention")
        
        # Manually expire the claim
        claim.status = ClaimStatus.EXPIRED
        claim.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        
        count = worker.cleanup_expired()
        
        assert count == 1
        assert worker.get_claim(claim.id) is None

    def test_active_count(self):
        """Active count reflects non-expired claims."""
        worker = ClaimWorker()
        worker.acquire("M1", "mention")
        worker.acquire("M2", "mention")
        
        assert worker.active_count() == 2

    def test_status_summary(self):
        """Status summary provides counts by status."""
        worker = ClaimWorker()
        c1 = worker.acquire("M1", "mention")
        c2 = worker.acquire("M2", "mention")
        worker.complete(c1.id, ClaimResult.SUCCESS)
        
        summary = worker.status_summary()
        
        assert summary["completed"] == 1
        assert summary["claimed"] == 1 or summary["active"] == 1