"""CLI entrypoint for init, poll, relay, run, and status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .imap_stage import initialize, poll_once
from .lock import InstanceLock
from .queue import Queue
from .relay import relay_once


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "poll", "relay", "run", "status"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--lock", type=Path)
    return parser


def _safe_failure(queue: Queue, exc: Exception) -> dict[str, object]:
    try:
        counts = queue.status()["counts"]
    except Exception:
        counts = {}
    return {
        "operation_failed": True,
        "error_type": type(exc).__name__,
        "counts": counts,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    lock_path = args.lock or args.queue.with_suffix(args.queue.suffix + ".lock")
    try:
        with InstanceLock(lock_path):
            with Queue(args.queue) as queue:
                if args.command == "status":
                    print(json.dumps(queue.status(), separators=(",", ":")))
                    return 0
                if args.config is None:
                    raise ConfigError("config_required")
                config = load_config(args.config)
                if args.command == "init":
                    result = initialize(queue, config)
                elif args.command == "poll":
                    result = poll_once(queue, config)
                elif args.command == "relay":
                    result = relay_once(queue, config)
                else:
                    poll_failed = False
                    relay_failed = False
                    try:
                        poll_result = poll_once(queue, config)
                    except Exception as exc:
                        poll_failed = True
                        poll_result = _safe_failure(queue, exc)
                    if not queue.collection_halted and not queue.relay_halted:
                        try:
                            relay_result = relay_once(queue, config)
                        except Exception as exc:
                            relay_failed = True
                            relay_result = _safe_failure(queue, exc)
                    else:
                        relay_result = {"skipped": "queue_halted", "counts": queue.status()["counts"]}
                    result = {"poll": poll_result, "relay": relay_result}
                    print(json.dumps(result, separators=(",", ":")))
                    return 1 if poll_failed or relay_failed else 0
                print(json.dumps(result, separators=(",", ":")))
                return 0
    except Exception:
        print(json.dumps({"operation_failed": True, "error_type": "worker_error"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
