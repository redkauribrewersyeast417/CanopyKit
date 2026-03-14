"""CanopyKit runtime package (internal Python package `canopykit`)."""

__version__ = "0.1.0"

from .runtime import (
    AgentMode,
    CoordinationSnapshot,
    EventEnvelope,
    EventAdapter,
    InboxSupervisor,
    ClaimWorker,
    ArtifactValidator,
    ModeManager,
    MetricsEmitter,
)
from .event_adapter import AgentEventFeedConfig, EventAdapter as CanopyEventAdapter, EventCursorState, FeedProbeResult, FeedSource, SQLiteCursorStore
from .inbox_supervisor import CanopyInboxSupervisor, InboxSupervisorConfig
from .artifact_validator import CanopyArtifactValidator
from .mode_manager import DefaultModeManager, FeedSourceState, ModeDecision, ModeThresholds
from .shadow_selftest import ShadowSelfTestConfig, ShadowSelfTestRunner, build_shadow_config
from .channel_bridge import ChannelBridge, ChannelBridgeConfig, ChannelRoutingDecision
from .channel_router import (
    CHANNEL_EVENT_TYPES,
    ChannelEventRouter,
    ChannelRouteOutcome,
    ChannelTaskCandidate,
)
from .subscription_policy import (
    SubscriptionDecision,
    SubscriptionScope,
    evaluate_subscription,
    subscription_diagnostics,
)
from .runloop import CanopyRunLoop, RunLoopConfig, RuntimeQueueStore, build_run_config
from .redaction import redact_secrets, REDACTED_PLACEHOLDER

__all__ = [
    "__version__",
    "AgentMode",
    "CoordinationSnapshot",
    "EventEnvelope",
    "EventAdapter",
    "InboxSupervisor",
    "ClaimWorker",
    "ArtifactValidator",
    "ModeManager",
    "MetricsEmitter",
    "CanopyEventAdapter",
    "AgentEventFeedConfig",
    "EventCursorState",
    "FeedSource",
    "FeedProbeResult",
    "SQLiteCursorStore",
    "CanopyInboxSupervisor",
    "InboxSupervisorConfig",
    "CanopyArtifactValidator",
    "DefaultModeManager",
    "FeedSourceState",
    "ModeDecision",
    "ModeThresholds",
    "ShadowSelfTestConfig",
    "ShadowSelfTestRunner",
    "build_shadow_config",
    "ChannelBridge",
    "ChannelBridgeConfig",
    "ChannelRoutingDecision",
    "CHANNEL_EVENT_TYPES",
    "ChannelEventRouter",
    "ChannelRouteOutcome",
    "ChannelTaskCandidate",
    "SubscriptionScope",
    "SubscriptionDecision",
    "evaluate_subscription",
    "subscription_diagnostics",
    "CanopyRunLoop",
    "RunLoopConfig",
    "RuntimeQueueStore",
    "build_run_config",
    "redact_secrets",
    "REDACTED_PLACEHOLDER",
]
