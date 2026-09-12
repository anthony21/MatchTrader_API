"""Launch the local dashboard (Vue assets must be built first)."""

import argparse
import os
import threading
import time
from pathlib import Path

from dotenv import dotenv_values

from ..capture.lifecycle import stopping
from ..capture.route import RouteConfig
from ..capture.tradingbox_forwarder import TradingBoxForwarder
from ..capture.ws_ingress import CaptureWebSocketServer
from ..core.settings import Settings
from .broker_profiles import BrokerProfiles, load_profile_names, load_profiles
from .broker_session import BrokerSession
from .controller import DashboardController
from .server import DashboardHTTPServer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop-file", type=Path, help="Local launcher shutdown signal")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--ws-port", type=int, help="Native WebSocket port; 0 disables (default 8767)")
    parser.add_argument("--port", type=int, default=8765)
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
    token = env.get("AQF_BRIDGE_TOKEN", "") or ""
    if token and (len(token) < 32 or not token.isascii() or any(c.isspace() for c in token)):
        parser.error(
            "AQF_BRIDGE_TOKEN must be a random secret with at least 32 non-whitespace ASCII characters"
        )
    try:
        ws_port = args.ws_port if args.ws_port is not None else int(env.get('AQF_CAPTURE_WS_PORT', '8767') or '8767')
        if not 0 <= ws_port <= 65535:
            raise ValueError()
    except ValueError:
        parser.error('AQF_CAPTURE_WS_PORT / --ws-port must be 0 through 65535')
    if ws_port and not token and args.ws_port is not None:
        parser.error('WebSocket capture requires AQF_BRIDGE_TOKEN')
    ledger = env.get("AQF_R01_LEDGER")
    accounts = [x.strip() for x in (env.get("AQF_ACCOUNT_IDS", "") or "").split(",") if x.strip()]
    profile_settings = load_profiles(args.env)
    controller = DashboardController(
        Settings.from_env(args.env),
        args.data,
        accounts=accounts,
        ledger_path=Path(ledger) if ledger else None,
        route=RouteConfig.model_validate_json(args.route.read_text()) if args.route else None,
        csv_limit=args.csv_limit,
        interactive_copying=True,
        p01_log_path=env.get('AQF_P01_LOG_PATH') or None,
        broker_session=BrokerSession(),
    )
    controller.broker_profiles = BrokerProfiles(profile_settings, controller, names=load_profile_names(args.env))
    controller.tradingbox_forwarder = TradingBoxForwarder(
        args.data / 'tradingbox-forwarding.json', controller.logging_events, controller.native_store.raw_log,
        api_key=env.get('TB_FORWARD_API_KEY') or '',
        auth_header=env.get('TB_FORWARD_AUTH_HEADER') or 'X-HCAMM-Key')
    try:
        if ws_port and token:
            controller.capture_websocket = CaptureWebSocketServer(controller, token, ws_port)
            controller.capture_websocket.start()
        with DashboardHTTPServer(
            ("0.0.0.0" if args.container else "127.0.0.1", args.port), controller, args.assets, token
        ) as server:
            print(
                f"Dashboard ready: http://127.0.0.1:{server.server_port} (capture stopped; no broker orders)",
                flush=True,
            )
            if args.stop_file:
                def watch_stop():
                    while not stopping(args.stop_file):
                        time.sleep(0.25)
                    server.shutdown()
                threading.Thread(target=watch_stop, daemon=True).start()
            server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        controller.close()


if __name__ == "__main__":
    main()
