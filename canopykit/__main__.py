"""CLI entrypoint for CanopyKit (internal Python package `canopykit`)."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Optional

from .config import CanopyKitConfig
from .metrics import metric_names
from .redaction import redact_secrets
from .runloop import CanopyRunLoop, build_run_config
from .shadow_selftest import ShadowSelfTestRunner, build_shadow_config

_PASS_LEVEL_RANK = {
    "failed": 0,
    "compatibility_pass": 1,
    "full_pass": 2,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canopykit",
        description="Canopy-native coordination runtime scaffolding for OpenClaw-style agents.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("print-metrics", help="Print the current core metric names.")
    subparsers.add_parser("print-config", help="Print the default runtime configuration.")

    shadow = subparsers.add_parser(
        "shadow-selftest",
        help="Run one deterministic shadow-mode validation cycle against a live Canopy node.",
    )
    shadow.add_argument("--config", type=Path, help="Optional JSON config file.")
    shadow.add_argument("--base-url", default="", help="Override Canopy base URL.")
    shadow.add_argument("--api-key", default="", help="Direct API key (prefer --api-key-file or env for normal use).")
    shadow.add_argument("--api-key-file", default="", help="Path to a file containing the API key.")
    shadow.add_argument("--agent-id", required=True, help="Stable agent identifier for cursor/metrics storage.")
    shadow.add_argument("--data-dir", default="data/canopykit", help="Directory for cursor state and local runtime data.")
    shadow.add_argument("--polls", type=int, default=3, help="How many event polls to run.")
    shadow.add_argument("--poll-interval", type=int, default=0, help="Seconds to wait between polls. Default 0 for fast validation.")
    shadow.add_argument("--heartbeat-fallback", type=int, default=30, help="Seconds of consecutive empty polls before heartbeat fallback would trigger.")
    shadow.add_argument("--event-limit", type=int, default=20, help="Event page size for each poll.")
    shadow.add_argument("--inbox-limit", type=int, default=5, help="How many actionable inbox rows to inspect.")
    shadow.add_argument("--request-timeout", type=float, default=10.0, help="HTTP request timeout in seconds.")
    shadow.add_argument(
        "--min-validation-level",
        choices=("compatibility_pass", "full_pass"),
        default="",
        help="Return nonzero unless the shadow self-test reaches at least this validation level.",
    )

    run = subparsers.add_parser(
        "run",
        help="Run the continuous CanopyKit coordination loop in daemon-mode shadow operation.",
    )
    run.add_argument("--config", type=Path, help="Optional JSON config file.")
    run.add_argument("--base-url", default="", help="Override Canopy base URL.")
    run.add_argument("--api-key", default="", help="Direct API key (prefer --api-key-file or env for normal use).")
    run.add_argument("--api-key-file", default="", help="Path to a file containing the API key.")
    run.add_argument("--agent-id", required=True, help="Stable agent identifier for cursor/metrics/runtime storage.")
    run.add_argument("--data-dir", default="data/canopykit", help="Directory for runtime state, queue, and metrics data.")
    run.add_argument("--poll-interval", type=int, default=0, help="Seconds between event polls. Default 0 uses config.")
    run.add_argument("--heartbeat-fallback", type=int, default=0, help="Seconds of consecutive empty polls before heartbeat fallback. Default 0 uses config.")
    run.add_argument("--request-timeout", type=float, default=10.0, help="HTTP request timeout in seconds.")
    run.add_argument("--event-limit", type=int, default=50, help="Event page size for each poll.")
    run.add_argument("--inbox-limit", type=int, default=0, help="How many actionable inbox rows to inspect. Default 0 uses config.")
    run.add_argument("--mark-seen", action="store_true", help="Mark pending inbox rows as seen during the runtime loop.")
    run.add_argument("--status-path", default="", help="Optional JSON status output path.")
    run.add_argument("--actions-path", default="", help="Optional JSONL action log output path.")
    run.add_argument("--max-cycles", type=int, default=0, help="Optional maximum runtime cycles before exit.")
    run.add_argument("--duration-seconds", type=int, default=0, help="Optional maximum wall time before exit.")

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "print-metrics":
        print(json.dumps({"metrics": metric_names()}, indent=2))
        return 0

    if args.command == "print-config":
        print(json.dumps(redact_secrets(asdict(CanopyKitConfig())), indent=2))
        return 0

    if args.command == "shadow-selftest":
        cfg = CanopyKitConfig.from_file(args.config) if args.config else None
        shadow_cfg = build_shadow_config(
            base_url=args.base_url,
            api_key=args.api_key,
            api_key_file=args.api_key_file,
            config=cfg,
            agent_id=args.agent_id,
            data_dir=args.data_dir,
            poll_interval_seconds=args.poll_interval,
            heartbeat_fallback_seconds=args.heartbeat_fallback,
            request_timeout_seconds=args.request_timeout,
            polls=args.polls,
            event_limit=args.event_limit,
            inbox_limit=args.inbox_limit,
        )
        runner = ShadowSelfTestRunner(shadow_cfg)
        try:
            result = runner.run()
            print(json.dumps(redact_secrets(result), indent=2))
        finally:
            runner.close()
        minimum = args.min_validation_level
        if minimum:
            actual = str((result.get("validation") or {}).get("status") or "failed")
            if _PASS_LEVEL_RANK.get(actual, 0) < _PASS_LEVEL_RANK[minimum]:
                return 1
        return 0

    if args.command == "run":
        cfg = CanopyKitConfig.from_file(args.config) if args.config else None
        run_cfg = build_run_config(
            base_url=args.base_url,
            api_key=args.api_key,
            api_key_file=args.api_key_file,
            config=cfg,
            agent_id=args.agent_id,
            data_dir=args.data_dir,
            poll_interval_seconds=args.poll_interval,
            heartbeat_fallback_seconds=args.heartbeat_fallback,
            request_timeout_seconds=args.request_timeout,
            event_limit=args.event_limit,
            inbox_limit=args.inbox_limit,
            mark_seen=args.mark_seen,
            status_path=args.status_path,
            actions_path=args.actions_path,
        )
        loop = CanopyRunLoop(run_cfg)
        try:
            result = loop.run(
                max_cycles=args.max_cycles or None,
                duration_seconds=args.duration_seconds or None,
            )
            print(json.dumps(redact_secrets(result), indent=2))
        finally:
            loop.close()
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
