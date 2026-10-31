"""Trusted OS-local administration. Never register as a model-facing tool."""

import argparse
import json
import os
import sys
from pathlib import Path

from .config import Config, ConfigError
from .policy import Thread
from .store import StoreError


def parser(result=None):
    if result is None:
        result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, default=os.environ.get("HERMES_THREAD_ASSIGNEE_CONFIG"))
    sub = result.add_subparsers(dest="command", required=True)
    for command in ("init", "status", "check", "show", "establish", "transfer", "clear"):
        item = sub.add_parser(command)
        if command in ("init", "establish", "transfer", "clear"):
            item.add_argument("--dry-run", action="store_true")
        if command in ("show", "establish", "transfer", "clear"):
            for field in ("workspace", "channel", "thread"):
                item.add_argument("--" + field, required=True)
        if command in ("establish", "transfer"):
            item.add_argument("--recipient", required=True, help="unique runtime profile within workspace")
        if command == "establish":
            item.add_argument("--if-absent", action="store_true", required=True)
        if command in ("transfer", "clear"):
            item.add_argument("--expected-revision", type=int, required=True)
            item.add_argument("--reason", required=True)
    return result


def main(argv=None):
    return run(parser().parse_args(argv))


def run(args):
    try:
        if args.config is None:
            raise ConfigError("explicit --config or HERMES_THREAD_ASSIGNEE_CONFIG required")
        config = Config.load(args.config)
        store = config.store()
        if args.command == "init":
            receipt = store.initialize(args.dry_run)
        elif args.command in ("status", "check"):
            receipt = store.check()
        else:
            key = Thread(args.workspace, args.channel, args.thread)
            if args.command == "show":
                recipient, revision = store.show(key)
                receipt = {
                    "thread": vars(key),
                    "recipient": recipient.as_dict() if recipient else None,
                    "revision": revision,
                }
            else:
                recipient = None
                if args.command != "clear":
                    matches = [
                        p
                        for p in config.participants
                        if p.workspace == args.workspace and p.runtime_profile == args.recipient
                    ]
                    if len(matches) != 1:
                        raise ConfigError("recipient must resolve uniquely in this workspace")
                    recipient = matches[0]
                receipt = store.change(
                    key,
                    recipient,
                    0 if args.command == "establish" else args.expected_revision,
                    "trusted local bootstrap" if args.command == "establish" else args.reason,
                    dry_run=args.dry_run,
                )
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (ConfigError, StoreError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
