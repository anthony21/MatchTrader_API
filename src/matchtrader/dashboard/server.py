"""Serve compiled Vue assets and a same-origin local control API."""

import hmac
import json
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..bridge.server import ingest
from .signals import MAX_SIGNAL

# B21 treats its configured endpoint as a base URL and appends this route.
SIGNAL_PATHS = frozenset({
    "/signals", "/events", "/capture/events",
    "/api/hcamm/events", "/signals/api/hcamm/events",
})


class DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address,
        controller,
        assets: Path,
        bridge_token: str = "",
        *,
        bind_and_activate=True,
        signal_hub=None,
        signal_port=8766,
    ):
        self.controller = controller
        self.assets = assets.resolve()
        self.signal_hub = signal_hub
        self.signal_port = signal_port
        self.session_token = secrets.token_urlsafe(32)
        super().__init__(address, Handler, bind_and_activate=bind_and_activate)

    def trusted(self, headers):
        host = headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}
        origin = headers.get("Origin")
        return (
            host in allowed
            and headers.get("Sec-Fetch-Site") != "cross-site"
            and (origin is None or origin == "http://" + host)
        )

    def authorized(self, headers):
        return hmac.compare_digest(headers.get("X-Session-Token", "").encode(), self.session_token.encode())


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(5)
        super().setup()

    def log_message(self, *args):
        pass

    def reply(self, status, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            f"default-src 'self'; connect-src 'self' ws://127.0.0.1:{getattr(self.server, 'signal_port', 8766)} ws://localhost:{getattr(self.server, 'signal_port', 8766)}; "
            "style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def do_GET(self):
        if not self.server.trusted(self.headers):
            return self.reply(403, {"error": "Local same-origin access required"})
        path = urlsplit(self.path).path
        if path == "/api/session":
            return self.reply(200, {"token": self.server.session_token})
        if path.startswith("/api/"):
            if not self.server.authorized(self.headers):
                return self.reply(401, {"error": "Reload the dashboard to start a new local session"})
            if path == "/api/status":
                status = self.server.controller.status()
                status["signal_port"] = getattr(self.server, "signal_port", 8766)
                return self.reply(200, status)
            if path == "/api/events":
                return self.reply(200, self.server.controller.feed())
            if path == "/api/capture/events":
                return self.reply(200, {"events": self.server.controller.native_store.feed()})
            return self.reply(404, {"error": "Unknown endpoint"})
        relative = "index.html" if path == "/" else unquote(path).lstrip("/")
        target = (self.server.assets / relative).resolve()
        if not target.is_relative_to(self.server.assets) or not target.is_file():
            return self.reply(404, {"error": "Asset not found; build the Vue frontend first"})
        return self.reply(
            200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        )

    def do_POST(self):
        if not self.server.trusted(self.headers):
            return self.reply(403, {"error": "Local same-origin access required"})
        signal_path = urlsplit(self.path).path
        if signal_path not in SIGNAL_PATHS and not self.server.authorized(
            self.headers
        ):
            return self.reply(401, {"error": "Reload the dashboard to start a new local session"})
        try:
            lengths = self.headers.get_all("Content-Length", [])
            length = int(lengths[0]) if len(lengths) == 1 else -1
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_SIGNAL or self.headers.get("Transfer-Encoding"):
            return self.reply(413, {"error": "Invalid request size"})
        try:
            body = self.rfile.read(length)
            if signal_path in SIGNAL_PATHS and getattr(
                self.server, "signal_hub", None
            ):
                from urllib.parse import parse_qs

                source = parse_qs(urlsplit(self.path).query).get("source", [""])[0][:200]
                return self.reply(202, self.server.signal_hub.publish(body, source))
            if self.path == "/capture/events":
                result = self.server.controller.receive_native(json.loads(body))
                return self.reply(202, result)
            if self.path == "/events":
                status, result = ingest(
                    "",
                    body,
                    "",
                    self.server.controller,
                )
                return self.reply(status, result)
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Invalid request")
            controller = self.server.controller
            if self.path == "/api/connect":
                result = controller.connect(payload.get("account_id"))
            elif self.path == "/api/brokers/select":
                result = controller.select_broker(payload.get("broker_id"))
            elif self.path == "/api/brokers/disconnect":
                result = controller.disconnect_broker(payload.get("broker_id"))
            elif self.path == "/api/start":
                result = controller.start(payload.get("account_id"))
            elif self.path == "/api/stop":
                result = controller.stop()
            elif self.path == "/api/orders/refresh":
                result = controller.refresh_orders()
            elif self.path == "/api/positions/refresh":
                result = controller.refresh_positions()
            elif self.path == "/api/copying":
                result = controller.set_copying(payload.get("enabled"))
            elif self.path == "/api/token/refresh":
                result = controller.refresh_session()
            else:
                return self.reply(404, {"error": "Unknown endpoint"})
            self.reply(200, result)
        except (ValueError, TypeError, KeyError):
            self.reply(
                400, {"error": "Action could not complete. Check the selected account and connection status."}
            )
        except TimeoutError:
            self.reply(408, {"error": "Request timed out"})
        except Exception:
            self.reply(
                500, {"error": "Local service error. Check the ledger path and restart the dashboard."}
            )
