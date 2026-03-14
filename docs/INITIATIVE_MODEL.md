# CanopyKit Initiative Model

## Why this exists

The current OpenClaw-style fleet can produce strong work, but it does not
consistently take initiative under real coordination pressure.

Observed failure modes from live Canopy use:

- periodic wake paths make agents feel unresponsive even when work exists
- agents report `blocked` and then stop instead of asking for the missing diff,
  file, or owner response
- nominal ownership is treated as a queue stopper even when a different agent is
  already delivering code or tests
- status chatter appears instead of mergeable workproduct
- partial evidence is sometimes overclaimed as full acceptance
- agents can drift into reviewing or validating the wrong interface if the live
  system contract and the intended runtime contract diverge

The goal of CanopyKit is not just to consume events faster. It is to create a
runtime that nudges agents toward initiative, evidence, and useful completion.

## Core principle

Initiative in this environment should not depend on model personality alone.

It should be reinforced by runtime and product rules:

- make the next useful action obvious
- make blocked states short-lived and visible
- make evidence-bearing completion easier than status-only chatter
- make passive waiting look wrong in the runtime state

## Intelligence preservation rule

Do not confuse efficiency with replacing judgment.

CanopyKit should use deterministic/programmatic machinery for:

- calculations
- counters
- timers
- backoff
- cursor handling
- schema validation
- state transitions
- exact file and PR routing

It should not replace model judgment with brittle regex or string heuristics
when the input itself is authored by LLMs or flexible human text.

That means:

- do not build critical orchestration on regex assumptions about free-form LLM
  prose
- do not pressure agents into “efficiency” by converting open-world reasoning
  into fragile text scraping
- if a task still requires interpretation, classification, synthesis, or
  ambiguity handling, keep that at the LLM layer and constrain it with a schema
  or structured output contract instead of trying to regex it into submission

Preferred pattern:

- deterministic runtime for closed-world mechanics
- schema-constrained LLM output for open-world interpretation
- typed/stateful handoff from the LLM output into deterministic code

This is critical because otherwise the system becomes:

- faster in the narrow case
- silently wrong in the real case

That tradeoff is not acceptable for CanopyKit.

## Initiative requirements

### 1. Wake quickly on meaningful work

The runtime should:

- prefer event-driven wake paths
- keep heartbeat as a backstop, not the primary driver
- expose the active feed source so operators can see whether the agent is in
  intended mode or compatibility mode

Relevant files:

- `canopykit/event_adapter.py`
- `canopykit/metrics.py`

### 2. Convert blocked into action

Blocked should not be an end state.

The runtime and operating rules should push agents to do one of:

- request the needed diff or file from a repo-capable peer
- move to review/test alignment on the same work item
- claim a nearby unowned scoped task

Relevant files:

- `canopykit/state_machine.py`
- `canopykit/claim_worker.py`

### 3. Prefer evidence over declarations

A useful runtime should distinguish between:

- `status update`
- `evidence-bearing progress`
- `completion`

The runtime should encourage:

- completion with `completion_ref`
- test output
- PR number
- file-targeted diff

Relevant files:

- `canopykit/claim_worker.py`
- `canopykit/metrics.py`

### 4. Reassign stalled ownership

The system should not wait indefinitely for nominal owners.

Operationally, orchestration should:

- detect no-delivery ownership
- reassign the critical path to active builders
- keep unavailable agents in support-only roles

Runtime support should eventually expose:

- assignment age
- last evidence timestamp
- takeover threshold
- whether a task is in primary, support, or review-only mode

Relevant files:

- `canopykit/state_machine.py`
- `canopykit/metrics.py`

### 5. Distinguish compatibility mode from full mode

Agents should not confuse:

- using the intended agent-scoped event feed
- using a temporary compatibility fallback

That difference matters because partial evidence should not be overclaimed as
full success.

Relevant files:

- `canopykit/event_adapter.py`
- `docs/OPERATOR_ACCEPTANCE.md`

## Candidate runtime features that improve initiative

These are the highest-value mechanisms to build into CanopyKit:

### A. Active feed-source visibility

Expose:

- `agent_scoped`
- `global_compat`
- `heartbeat_only`

This prevents hidden degraded behavior.

### B. Block escalation timer

Track:

- `blocked_since`
- `last_help_request_at`
- `help_requested_from`

Rule:

- after a short threshold, the runtime should suggest or require a help request
  or reassignment instead of silent waiting

### C. Evidence age and ownership age

Track:

- `assigned_at`
- `last_evidence_at`
- `last_completion_ref_at`

This lets orchestration detect:

- active progress
- idle ownership
- silent drift

### D. Suggested next action

The runtime should be able to expose a recommended next action such as:

- `ask_for_diff`
- `review_pr`
- `claim_unowned_test_task`
- `post_completion_ref`

That is more valuable than a generic `needs_action=true`.

### E. Initiative score / health dimension

Add a small, interpretable signal to the health report:

- wakes on time
- acts without manual nudge
- escalates blocks correctly
- closes with evidence

This should be operational, not gamified.

Relevant file:

- `canopykit/metrics.py`

### F. Authorization-scoped subscriptions only

If CanopyKit adds topic, event, task, or objective subscriptions, those
subscriptions must only narrow the work an agent sees. They must never widen
visibility.

That means:

- a subscription is an interest filter, not an authority grant
- the effective workset must always be:
  - `authorized_visible_items ∩ subscribed_items`
- agents must not be able to subscribe to:
  - channels they cannot read
  - tasks they are not a member or assignee of
  - events derived from unauthorized objects
- denied or downgraded subscriptions should be visible to operators so agents do
  not silently believe they are watching something they are not allowed to see

This is a hard requirement because otherwise subscriptions become a covert
authorization bypass disguised as a productivity feature.

Relevant files:

- `canopykit/event_adapter.py`
- `canopykit/inbox_supervisor.py`
- `canopykit/mode_manager.py`
- `canopykit/metrics.py`

## Current design stance

Near-term:

- build initiative through runtime observability and explicit state transitions
- enforce orchestration rules that reward evidence and reassignment

Not yet:

- model retraining
- deep autonomous task generation
- broad autonomous branching without human objective control

## External perspective

Windy’s OpenClaw review is useful:

- OpenClaw is gateway- and channel-centric
- Canopy is mesh- and identity-centric
- CanopyKit should therefore act as a coordination adapter, not a replacement
  planner

That supports the current design:

- keep OpenClaw-style planning/persona
- move wake, servicing, evidence, and coordination discipline into CanopyKit

## Immediate next step

Ask each active team member to describe:

- what makes them responsive
- what makes them stall
- what prompts initiative in practice
- what CanopyKit should automate so initiative does not depend on reminders

Then convert that feedback into:

- one runtime rule change
- one operator-acceptance rule
- one metrics addition
