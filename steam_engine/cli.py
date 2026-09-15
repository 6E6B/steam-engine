"""steam-engine CLI — generic driver commands only."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .cdp import list_targets
from .client import SteamEngine
from .enable import enable as _enable


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="steam-engine",
        description="Drive a running Steam client's internal JS (SteamClient.*, window.* stores) over CDP",
    )
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("STEAM_CDP_PORT", "1337")),
                   help="remote-debugging port (env STEAM_CDP_PORT)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="probe the CDP endpoint")
    sub.add_parser("targets", help="list debuggable targets")
    e = sub.add_parser("enable", help="patch webhelper wrapper (Linux)")
    e.add_argument("--restart", action="store_true",
                   help="kill steamwebhelper so Steam respawns it patched")
    ev = sub.add_parser("eval", help="evaluate raw JS in SharedJSContext")
    ev.add_argument("expr")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.cmd == "enable":
        print(_enable(args.port, restart=args.restart))
        return 0
    if args.cmd == "status":
        st = SteamEngine.status(args.port)
        print(json.dumps(st, indent=2))
        return 0 if st["reachable"] else 1
    if args.cmd == "targets":
        for t in list_targets(args.port):
            print(f"{t.kind:<10} {t.title:<35} {t.url[:80]}")
        return 0
    if args.cmd == "eval":
        with SteamEngine.connect(args.port) as se:
            print(json.dumps(se.eval(args.expr), indent=2, default=str))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
