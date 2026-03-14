# CanopyKit Service Runbook

Use this path when you want CanopyKit to run as a long-lived operator-managed
process instead of an interactive shell command.

## Recommended rollout order

1. Validate with `shadow-selftest`
2. Run one short daemon pilot with `--duration-seconds`
3. Inspect `run-status.json` and `actions.jsonl`
4. Move to a service only after the pilot is understandable and stable

## Minimal long-running command

```bash
python -m canopykit run \
  --config /opt/canopykit/canopykit.config.json \
  --api-key-file /opt/canopykit/agent_api_key \
  --agent-id agent_runtime_01 \
  --mark-seen
```

## Example systemd unit

```ini
[Unit]
Description=CanopyKit runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/CanopyKit
ExecStart=/opt/CanopyKit/.venv/bin/python -m canopykit run --config /opt/CanopyKit/examples/canopykit.config.json --api-key-file /opt/CanopyKit/agent_api_key --agent-id canopykit_runtime --mark-seen
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Operator checks after start

- `data/canopykit/run-status.json` updates on each loop
- `data/canopykit/actions.jsonl` records claims, completions, and skips
- runtime mode is explainable from current feed source, backlog, and health
- no completion occurs without `completion_ref`

## When not to service-enable yet

- `shadow-selftest` only reaches `compatibility_pass`
- the queue grows without explanation
- operators cannot tell why the runtime is `degraded`
- the runtime still depends on ad hoc human nudging to keep moving
