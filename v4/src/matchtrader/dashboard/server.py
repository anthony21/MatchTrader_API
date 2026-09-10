"""Serve compiled Vue assets and a same-origin local control API."""

import hmac
import json
import mimetypes
import secrets
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore, Event
from urllib.parse import unquote, urlsplit

from ..bridge.server import MAX_BODY, ingest
from ..capture.meaning import catalog


class DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, controller, assets: Path, bridge_token: str, *, bind_and_activate=True):
        self.controller = controller
        self.assets = assets.resolve()
        self.bridge_token = bridge_token
        self.session_token = secrets.token_urlsafe(32)
        self.stream_slots = BoundedSemaphore(8)
        self.stream_stop = Event()
        super().__init__(address, Handler, bind_and_activate=bind_and_activate)

    def server_close(self):
        self.stream_stop.set()
        self.controller.native_store.notify_stream()
        super().server_close()

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
            "default-src 'self'; connect-src 'self'; "
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
            if path == "/api/capture/stream":
                return self.stream_native()
            if path == "/api/copy-settings":
                return self.reply(200, self.server.controller.copy_settings())
            if path == "/api/event-meanings":
                return self.reply(200, catalog())
            if path == "/api/status":
                return self.reply(200, self.server.controller.status())
            if path == "/api/events":
                return self.reply(200, self.server.controller.feed())
            if path == "/api/capture/events":
                return self.reply(200, {"events": self.server.controller.native_store.feed()})
            if path == "/api/trade-mappings":
                controller = self.server.controller
                with controller.lock:
                    return self.reply(200, {"account_id": controller.selected,
                                           "mappings": controller.native_store.mapping_view(controller.selected)})
            return self.reply(404, {"error": "Unknown endpoint"})
        relative = "index.html" if path == "/" else unquote(path).lstrip("/")
        target = (self.server.assets / relative).resolve()
        if not target.is_relative_to(self.server.assets) or not target.is_file():
            return self.reply(404, {"error": "Asset not found; build the Vue frontend first"})
        return self.reply(
            200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        )

    def stream_native(self):
        if not self.server.stream_slots.acquire(blocking=False):
            return self.reply(503, {"error": "Too many open event streams"})
        self.close_connection = True
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            revision = -1
            while not self.server.stream_stop.is_set():
                snapshot = self.server.controller.native_store.stream_snapshot(revision)
                if snapshot is None or self.server.stream_stop.is_set():
                    break
                revision = snapshot["revision"]
                data = ("data: " + json.dumps(snapshot) + "\n\n").encode() if "events" in snapshot else b": heartbeat\n\n"
                self.wfile.write(data)
                self.wfile.flush()
        except (OSError, TimeoutError):
            pass  # Disconnected/slow readers never block capture or routing.
        finally:
            self.server.stream_slots.release()

    def do_POST(self):
        if not self.server.trusted(self.headers):
            return self.reply(403, {"error": "Local same-origin access required"})
        if self.path not in {"/events", "/capture/events"} and not self.server.authorized(self.headers):
            return self.reply(401, {"error": "Reload the dashboard to start a new local session"})
        try:
            lengths = self.headers.get_all("Content-Length", [])
            length = int(lengths[0]) if len(lengths) == 1 else -1
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
            return self.reply(413, {"error": "Invalid request size"})
        try:
            body = self.rfile.read(length)
            if self.path == "/capture/events":
                token = self.server.bridge_token
                if not token or not hmac.compare_digest(
                    self.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()
                ):
                    return self.reply(401, {"error": "Sender authentication required"})
                result = self.server.controller.receive_native(json.loads(body))
                return self.reply(202, result)
            if self.path == "/events":
                if not self.server.bridge_token:
                    return self.reply(503, {"error": "Configure the bridge token before attaching a sender"})
                status, result = ingest(
                    self.headers.get("Authorization", ""),
                    body,
                    self.server.bridge_token,
                    self.server.controller,
                )
                return self.reply(status, result)
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Invalid request")
            controller = self.server.controller
            if self.path == "/api/connect":
                result = controller.connect(payload.get("account_id"))
            elif self.path == "/api/start":
                result = controller.start(payload.get("account_id"))
            elif self.path == "/api/stop":
                result = controller.stop()
            elif self.path == "/api/orders/refresh":
                result = controller.refresh_orders()
            elif self.path == "/api/positions/refresh":
                result = controller.refresh_positions()
            elif self.path == "/api/copy-settings":
                result = controller.configure_copying(payload)
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
