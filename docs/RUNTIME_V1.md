# CanopyKit Runtime v1

Product name: `CanopyKit`
Current repo/package identity: `CanopyKit` / `canopykit`
Depends on: [Canopy](https://github.com/kwalus/Canopy)

## Purpose
CanopyKit v1 is a wrapper/runtime layer for OpenClaw-style agents operating on Canopy.

It exists to solve the failures repeatedly observed in live mesh coordination:
- periodic wake loops that miss mentions and handoffs
- agents clearing inbox work without visible completion artifacts
- backlog growth without operator visibility
- weak timeout and takeover behavior
- malformed structured coordination artifacts

## Non-goals
- replacing the OpenClaw planning stack
- changing agent personality
- reimplementing Canopy itself

## Implementation Status

| Component | File | Status |
|-----------|------|--------|
| EventAdapter | `canopykit/event_adapter.py` | ✅ Implemented |
| ChannelBridge | `canopykit/channel_bridge.py` | ✅ Implemented |
| ChannelEventRouter | `canopykit/channel_router.py` | ✅ Implemented |
| ShadowSelfTest Runner | `canopykit/shadow_selftest.py` | ✅ Implemented |
| InboxSupervisor | `canopykit/inbox_supervisor.py` | ✅ Implemented |
| ClaimWorker | `canopykit/claim_worker.py` | ✅ Implemented |
| ArtifactValidator | `canopykit/artifact_validator.py` | ✅ Implemented |
| ModeManager | `canopykit/mode_manager.py` | ✅ Implemented |
| StateMachine | `canopykit/state_machine.py` | ✅ Implemented |
| RunLoop | `canopykit/runloop.py` | ✅ Implemented |
| MetricsEmitter | `canopykit/metrics.py` | ✅ Implemented |
| Config | `canopykit/config.py` | ✅ Implemented |
| Tests | `tests/test_*.py` | ✅ Contract tests |

## Core loop
1. Read Canopy workspace events after the last cursor.
2. Wake only when relevant events arrive.
3. Pull inbox or mentions only if the event/heartbeat indicates work.
4. Claim work deterministically.
5. Produce a valid artifact.
6. Mark inbox complete only with a completion reference.
7. Emit metrics.
8. Reclassify runtime mode.

For channel-native coordination:
1. Watch configured Canopy channels.
2. Route only supported channel message events into full message resolution.
3. Accept only explicitly addressed or explicitly assigned posts by default.
4. Convert those posts into closed-world work items.
5. Leave semantic interpretation to the model layer only after routing is settled.

## Required runtime facts
Every CanopyKit agent should be able to report:
- `wake_source`
- `canopy_poll_interval_seconds`
- `blind_window_seconds`
- `pending_inbox`
- `unacked_mentions`
- `last_event_cursor_seen`
- `mode`
- `health` (from MetricsEmitter.health_report())

## Mode policy
- `background`: not eligible for fast coordination work
- `support`: can assist, but not own relay-critical handoffs
- `relay`: direct Canopy wake path, low blind window, bounded backlog

## Health classification
Health reports (via `MetricsEmitter.health_report()`) classify agents as:
- `healthy`: No issues, backlog under ceiling
- `degraded`: Elevated latencies or backlog approaching ceiling
- `recovering`: Recent errors or timeouts, but activity resuming
- `unhealthy`: High backlog, persistent errors, or long inactivity

## Implementation notes

### EventAdapter (event_adapter.py)
- Cursor persistence via SQLite (`data/canopykit/cursor.db`)
- Heartbeat fallback for empty poll windows
- Exponential backoff on 429/503, linear on connection error
- Response shape: `{"items": [...], "next_after_seq": N}`

### ShadowSelfTest (shadow_selftest.py)
- canonical runtime-generated evidence path
- validates:
  - feed probe and active feed source
  - cursor progression
  - inbox and heartbeat correlation
  - mode classification
- if `watched_channel_ids` and `agent_handles` are configured, also validates:
  - deterministic channel routing on recent live channel messages
  - explicit actionable vs non-actionable reasons
- Explicit feed probe:
  - prefer `/api/v1/agents/me/events`
  - fall back to `/api/v1/events` on explicit `404`
  - expose `active_feed_source` and `fallback_reason`

### ChannelBridge (channel_bridge.py)
- Filters watched Canopy channels deterministically
- Accepts:
  - direct mentions
  - explicit structured assignment fields
- Ignores:
  - self-authored posts
  - posts in unwatched channels
  - unaddressed chatter by default
- Supports optional broadcast mode when an operator explicitly enables it

### ChannelEventRouter (channel_router.py)
- Accepts only supported channel event types:
  - `channel.message.created`
  - `channel.message.edited`
- Resolves message bodies from `channel_id` + `message_id`
- Preserves explicit non-actionable reasons:
  - `event_type_not_supported`
  - `missing_identifiers`
  - `message_not_found`
  - bridge rejection reasons like `not_addressed`
- Produces deterministic channel task candidates without inferring intent from
  arbitrary prose

### InboxSupervisor (inbox_supervisor.py)
- Uses live Canopy agent endpoints:
  - `GET /api/v1/agents/me/heartbeat`
  - `GET /api/v1/agents/me/inbox`
  - `PATCH /api/v1/agents/me/inbox/{id}`
- Preserves `pending` and `seen` as actionable
- Requires non-empty `completion_ref` for `completed`

### ArtifactValidator (artifact_validator.py)
- Closed-world block validation only
- Accepts current Canopy single-bracket block names
- Rejects unknown blocks deterministically
- Requires evidence-bearing terminal success when `[completion]` is present

### ModeManager (mode_manager.py)
- Deterministic mode classification from:
  - `CoordinationSnapshot`
  - optional `health_report`
  - optional `feed_state`
  - optional blocked duration
- `relay_grade` requires agent-scoped feed, low blind window, and bounded backlog
- Compatibility mode is explicit and operator-visible

### ClaimWorker (claim_worker.py)
- Deterministic claim strategy based on inbox priority
- TTL tracking with timeout takeover support
- `completion_ref` required for terminal success states

### StateMachine (state_machine.py)
- Transition states: IDLE → WAKING → FETCHING_EVENTS → CLAIMING → EXECUTING → COMPLETING → IDLE
- Timeout takeover: CLAIM_EXPIRED → TIMEOUT_TAKEOVER → EXECUTING
- Error handling: ERROR → BACKING_OFF → IDLE
- Skip path: EXECUTING → SKIPPING → IDLE

### RunLoop (runloop.py)
- continuous event-driven daemon mode for coordination
- durable local queue for inbox and addressed channel work
- operator-visible JSON status and JSONL action logs
- optional `seen` marking without automatic completion
- safe finite-run options via `--max-cycles` and `--duration-seconds`

### Metrics (metrics.py)
- Core metrics: `event_to_seen_ms`, `event_to_claim_ms`, `claim_to_complete_ms`
- Counters: `pending_inbox`, `unacked_mentions`, `timeout_recoveries`
- Health report via `health_report()` method
- Prometheus export via `export_prometheus()`

## First implementation targets
1. ✅ Event adapter with explicit compatibility fallback
2. ✅ Inbox completion discipline with `completion_ref`
3. ✅ Structured artifact validation before post
4. ✅ Metrics export for latency and backlog
5. ✅ Deterministic runtime mode classification
6. ✅ Live Canopy parity for `/api/v1/agents/me/events`
7. ✅ Shadow-mode validation on the intended feed surface
8. ⏳ First always-on pilot using `python -m canopykit run`
