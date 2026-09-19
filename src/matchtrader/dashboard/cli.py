"""Launch the local dashboard (Vue assets must be built first)."""

import argparse
import os
from pathlib import Path

from dotenv import dotenv_values

from ..capture.route import RouteConfig
from ..sessions.profiles import load_profiles
from .broker_dashboard import BrokerDashboard
from .server import DashboardHTTPServer
from .signals import SignalHub, SignalServer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--signal-port", type=int, default=8766)
    parser.add_argument("--assets", type=Path, default=Path("frontend/dist"))
    parser.add_argument("--data", type=Path, default=Path("data/dashboard"))
    parser.add_argument("--route", type=Path, help="Explicit Quantower route JSON; copying starts disarmed")
    parser.add_argument("--csv-limit", type=int, default=1000)
    parser.add_argument(
        "--container", action="store_true", help="Bind container interface; publish to host loopback only"
    )
    args = parser.parse_args(argv)
    if not (args.assets / "index.html").is_file():
        parser.error("Build Vue first: npm --prefix frontend ci && npm --prefix frontend run build")
    env = {**dotenv_values(args.env), **os.environ}
    ledger = env.get("MTR_R01_LEDGER")
    accounts = [x.strip() for x in (env.get("MTR_ACCOUNT_IDS", "") or "").split(",") if x.strip()]
    controller = BrokerDashboard(
        load_profiles(env),
        args.data,
        accounts=accounts,
        ledger_path=Path(ledger) if ledger else None,
        route=RouteConfig.model_validate_json(args.route.read_text()) if args.route else None,
        csv_limit=args.csv_limit,
    )
    hub = SignalHub(args.data / "signals.sqlite3")
    try:
        with (
            SignalServer(hub, args.signal_port) as signals,
            DashboardHTTPServer(
                ("0.0.0.0" if args.container else "127.0.0.1", args.port),
                controller,
                args.assets,
                signal_hub=hub,
                signal_port=signals.port,
            ) as server,
        ):
            print(
                f"Dashboard ready: http://127.0.0.1:{server.server_port} (capture stopped; no broker orders)",
                flush=True,
            )
            server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        controller.close()
        hub.close()


if __name__ == "__main__":
    main()
