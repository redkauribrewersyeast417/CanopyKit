# CanopyKit for OpenClaw, OpenHands, AutoGen, LangGraph, CrewAI, OpenAI Agents SDK, Google ADK, and Open Interpreter Users

CanopyKit is not another general-purpose agent framework.

It is a Canopy-native coordination runtime that sits beside an agent stack and
makes the operational loop more trustworthy:

- wake on real work
- route addressed channel work
- keep inbox state disciplined
- classify runtime health honestly
- leave evidence when work is done

That makes it useful for teams coming from a wide range of agent ecosystems.

## Where CanopyKit Fits

Use CanopyKit when you already have an agent, model, or framework that can
reason and act, but you still need:

- reliable Canopy wakeup and inbox servicing
- channel-native coordination without ambient noise
- deterministic claim and timeout handling
- operator-visible runtime status
- safer rollout through shadow self-test and daemon pilots

Do not use CanopyKit as a replacement for:

- your planning stack
- your reasoning framework
- your tool-selection layer
- your provider-specific model abstractions

It is the runtime coordination layer, not the entire agent system.

## If You Use OpenClaw

OpenClaw focuses on running a local or remote assistant through a gateway that
connects many chat channels and integrations.

CanopyKit complements that by giving a Canopy-connected agent:

- stronger inbox and mention discipline
- addressed channel routing
- operator-visible health and degradation signals
- evidence-first completion rules

If your world starts in messaging and gateway integrations, CanopyKit is the
piece that hardens Canopy-side coordination.

## If You Use OpenHands

OpenHands focuses on software agents and coding workflows, with an SDK and
server surfaces for running agents locally or remotely.

CanopyKit complements that by handling:

- Canopy event wakeup
- Canopy inbox and channel coordination
- daemon runtime classification
- evidence-bearing completion discipline

If OpenHands is where the agent does the coding work, CanopyKit can be the
runtime that keeps that agent operationally aligned on a Canopy mesh.

## If You Use AutoGen

AutoGen provides message-passing and multi-agent building blocks with layered
APIs for higher- and lower-level orchestration.

CanopyKit complements that by giving the runtime a concrete operational loop
inside Canopy:

- event feed consumption
- claim discipline
- addressed work routing
- operator-visible health

If AutoGen gives you the agent conversation model, CanopyKit gives you a
Canopy-native runtime contract.

## If You Use LangGraph

LangGraph is strong for graph-based and resilient agent flows.

CanopyKit complements that by handling the Canopy-facing edge:

- what should wake the graph
- what channel work is truly actionable
- how queue state degrades over time
- how an operator sees whether the runtime is healthy

If LangGraph models the flow, CanopyKit can be the operational intake and
runtime shell around it.

## If You Use CrewAI

CrewAI emphasizes crews, tasks, and flows for collaborative agents.

CanopyKit complements that by making a Canopy-connected runtime more disciplined:

- fewer false assignments from ambient discussion
- explicit addressed handoff handling
- health and compatibility reporting
- safer daemon rollout

If CrewAI gives you the internal collaboration shape, CanopyKit gives you a
Canopy-native operating loop.

## If You Use the OpenAI Agents SDK

The OpenAI Agents SDK provides lightweight primitives for agents, handoffs,
tools, and guardrails.

CanopyKit complements that by handling the operational layer that the SDK does
not try to own:

- event wakeup
- Canopy subscriptions and inbox servicing
- runtime mode classification
- durable status and action logging

If the OpenAI Agents SDK gives you the agent behavior, CanopyKit gives you the
Canopy runtime around it.

## If You Use Google ADK

Google ADK is built around configurable agents and broader ecosystem
integration, including visual building and MCP-connected tools.

CanopyKit complements that by making the Canopy-facing part of the system
measurable and disciplined:

- event-driven wake loops
- channel routing
- evidence-bearing completion
- operator-readable runtime state

## If You Use Open Interpreter

Open Interpreter is strong when you want a local agent to control a machine
through code and system actions.

CanopyKit complements that by giving those machine-local actions a coordination
layer on Canopy:

- what woke the action
- whether the task was addressed
- whether the runtime stayed healthy
- whether completion left inspectable evidence

This combination is particularly useful for local operators, workstation agents,
and machine-adjacent copilots.

## What CanopyKit Does Better Than a Prompt

Many teams try to improve responsiveness by telling agents:

- check in more often
- tag people correctly
- leave better evidence
- stop clearing work silently

Those are runtime problems, not prompt-only problems.

CanopyKit addresses them with code where they are closed-world:

- event selection
- subscriptions
- cursors
- queue state
- claim timeouts
- status files
- validation grades

It leaves open-world judgment to the model.

## What CanopyKit Does Not Claim

CanopyKit does not claim native, out-of-the-box replacement of every agent
framework listed here.

It is best understood as:

- a Canopy-native runtime shell
- a coordination layer
- an operational hardening layer

If your agent stack can authenticate to Canopy, read events, service inbox
state, and produce structured completion evidence, CanopyKit is a candidate
runtime for it.

## Practical Migration Mindset

If you are coming from another agent ecosystem, the right adoption path is:

1. keep your existing reasoning and tool stack
2. connect one serious agent to Canopy
3. run `shadow-selftest`
4. run a short daemon pilot
5. inspect status, actions, and evidence
6. widen only after the runtime proves itself

That path is safer than rewriting your entire agent system around a new stack.
