"""Run a shadow receiver or bounded observation of fresh R01 ledger activity."""

import argparse
import json
import os
from pathlib import Path

from dotenv import dotenv_values

from .api import ShadowBridge
from .ledger import observe
from .server import serve


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--journal", type=Path, default=Path("data/bridge/shadow.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    receiver = commands.add_parser("serve", help="Listen on 127.0.0.1; never submit broker orders")
    receiver.add_argument("--port", type=int, default=8765)
    observer = commands.add_parser("observe", help="Observe only lines appended after startup")
    observer.add_argument("--ledger", type=Path, required=True)
    observer.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args(argv)
    env = {**dotenv_values(args.env), **os.environ}
    account = env.get("MTR_ACCOUNT_ID", "")
    if not account:
        parser.error("Set MTR_ACCOUNT_ID in .env")
    with ShadowBridge(account, args.journal) as bridge:
        if args.command == "serve":
            print(f"Shadow receiver: http://127.0.0.1:{args.port}/events (no broker orders)", flush=True)
            serve(bridge, port=args.port)
        else:
            result = observe(args.ledger, bridge.journal, seconds=args.seconds)
            result["intended_account_id"] = account
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
