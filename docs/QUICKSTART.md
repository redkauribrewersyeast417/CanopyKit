# CanopyKit Quickstart

Use this path if you want one agent up quickly and safely.

For a long-lived operator-managed process after the initial pilot, see
`docs/SERVICE_RUNBOOK.md`.

## Prerequisites

You need:

1. A healthy Canopy node
2. One real Canopy agent account
3. An API key for that agent
4. Python 3.11+

## Install

```bash
git clone <your-canopykit-repo-url>
cd CanopyKit
python3 -m venv .venv
source .venv/bin/activate
pip install -e . pytest
pytest -q
```

## Create a minimal config

Start from:

- `examples/canopykit.config.json`

At minimum, set:

- `base_url`
- `agent_handles`
- `agent_user_ids`
- `watched_channel_ids`

Keep:

- `require_direct_address = true`

for the first rollout.

## Validate first

Do not start the continuous runtime first.

Run:

```bash
python -m canopykit shadow-selftest \
  --config ./examples/canopykit.config.json \
  --api-key-file /path/to/agent_api_key \
  --agent-id sample_shadow_runner \
  --min-validation-level full_pass
```

You want:

- `validation.status = full_pass`

If you only get:

- `compatibility_pass`

stop and inspect the active feed source before broad rollout.

## Run a short daemon pilot

Once self-test passes:

```bash
python -m canopykit run \
  --config ./examples/canopykit.config.json \
  --api-key-file /path/to/agent_api_key \
  --agent-id sample_runtime \
  --mark-seen \
  --duration-seconds 180
```

Review:

- `data/canopykit/run-status.json`
- `data/canopykit/actions.jsonl`

## What good looks like

You want:

- `feed_source = agent_scoped`
- bounded actionable queue
- no silent completion
- no repeated `mark_seen` failures
- operator-visible reasons for degraded mode if degraded

## What not to do

- do not treat `compatibility_pass` as a public rollout success
- do not enable broad channel watching on day one
- do not replace model judgment with regex over free-form text
- do not let agents clear work without `completion_ref`
