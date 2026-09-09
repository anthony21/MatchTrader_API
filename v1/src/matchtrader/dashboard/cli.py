"""Launch the local dashboard (Vue assets must be built first)."""

import argparse
import os
from pathlib import Path

from dotenv import dotenv_values

from ..core.settings import Settings
from .controller import DashboardController
from .server import DashboardHTTPServer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--assets", type=Path, default=Path("frontend/dist"))
    parser.add_argument("--data", type=Path, default=Path("data/dashboard"))
    parser.add_argument(
        "--container", action="store_true", help="Bind container interface; publish to host loopback only"
    )
    args = parser.parse_args(argv)
    if not (args.assets / "index.html").is_file():
        parser.error("Build Vue first: npm --prefix frontend ci && npm --prefix frontend run build")
    env = {**dotenv_values(args.env), **os.environ}
    token = env.get("MTR_BRIDGE_TOKEN", "") or ""
    if token and (len(token) < 32 or not token.isascii() or any(c.isspace() for c in token)):
        parser.error(
            "MTR_BRIDGE_TOKEN must be a random secret with at least 32 non-whitespace ASCII characters"
        )
    ledger = env.get("MTR_R01_LEDGER")
    accounts = [x.strip() for x in (env.get("MTR_ACCOUNT_IDS", "") or "").split(",") if x.strip()]
    controller = DashboardController(
        Settings.from_env(args.env),
        args.data,
        accounts=accounts,
        ledger_path=Path(ledger) if ledger else None,
    )
    try:
        with DashboardHTTPServer(
            ("0.0.0.0" if args.container else "127.0.0.1", args.port), controller, args.assets, token
        ) as server:
            print(
                f"Dashboard ready: http://127.0.0.1:{server.server_port} (capture stopped; no broker orders)",
                flush=True,
            )
            server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        controller.close()


if __name__ == "__main__":
    main()
