"""Serve compiled Vue assets and a same-origin local control API."""

import base64
import hmac
import json
import mimetypes
import secrets
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore, Event
from urllib.parse import parse_qs, unquote, urlsplit

from ..bridge.server import MAX_BODY, ingest
from ..capture.logging_store import MAX_LOG_BODY
from ..capture.meaning import catalog
from ..capture.tradingbox_forwarder import MAX_REQUEST, end_to_end, validate_target


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
        if self.path.startswith('/api/hcamm/'):
            return self.forward_tradingbox()
        if not self.server.trusted(self.headers):
            return self.reply(403, {"error": "Local same-origin access required"})
        path = urlsplit(self.path).path
        if path == "/api/session":
            return self.reply(200, {"token": self.server.session_token})
        if path.startswith("/api/"):
            if not self.server.authorized(self.headers):
                return self.reply(401, {"error": "Reload the dashboard to start a new local session"})
            if path == "/api/raw/stream":
                return self.stream_native(raw=True)
            if path == "/api/capture/stream":
                return self.stream_native()
            if path == '/api/tradingbox-forwarding':
                forwarder = self.server.controller.tradingbox_forwarder
                return self.reply(200, forwarder.status() if forwarder else {'enabled': False, 'live': False, 'key_configured': False, 'url': ''})
            if path == "/api/copy-settings":
                return self.reply(200, self.server.controller.copy_settings())
            if path == "/api/event-meanings":
                return self.reply(200, catalog())
            if path == "/api/status":
                return self.reply(200, self.server.controller.status())
            if path == '/api/broker-profiles':
                profiles = self.server.controller.broker_profiles
                return self.reply(200, profiles.snapshot() if profiles else {'profiles': [], 'limit': 5})
            if path == '/api/logging/events':
                try:
                    before = int(parse_qs(urlsplit(self.path).query).get('before', ['0'])[0])
                    result = self.server.controller.logging_events.feed(before)
                    # Browser previews are redacted; exact bytes stay in the private archive.
                    for record in result['records']:
                        record.pop('data_base64', None)
                    return self.reply(200, result)
                except ValueError:
                    return self.reply(400, {'error': 'Invalid logging cursor'})
            if path == '/api/relay/logs':
                try:
                    after = int(parse_qs(urlsplit(self.path).query).get('after', ['0'])[0])
                    return self.reply(200, self.server.controller.relay_logs.feed(after))
                except ValueError:
                    return self.reply(400, {'error': 'Invalid relay log cursor'})
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

    def stream_native(self, raw=False):
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
                store = self.server.controller.native_store
                snapshot = (store.raw_log if raw else store).stream_snapshot(revision)
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

    def forward_tradingbox(self):
        self.close_connection = True
        if not self.server.trusted(self.headers):
            return self.reply(403, {'error': 'Local same-origin access required'})
        forwarder = self.server.controller.tradingbox_forwarder
        headers = list(self.headers.raw_items())
        if self.headers.get('Origin') is not None or not forwarder or not forwarder.authorized(headers):
            return self.reply(401, {'error': 'TradingBox sender authentication required'})
        try:
            validate_target(self.path)
            ticket = forwarder.ticket()
            body = self.read_forward_body()
        except (ValueError, OSError):
            return self.reply(400, {'error': 'Invalid or incomplete TradingBox request framing or target'})
        try:
            status, reason, headers, payload = forwarder.receive(
                headers, body, ticket, method=self.command, target=self.path)
        except Exception:
            return self.reply(503, {'error': 'Request could not be recorded; forwarding aborted'})
        # Do not inject dashboard Server/Date/cache headers into upstream replies.
        self.send_response_only(status, reason.replace('\r', '').replace('\n', ''))
        for name, value in end_to_end(headers):
            self.send_header(name, value)
        if self.command == 'HEAD' or status == 304:
            for name, value in headers:
                if name.lower() == 'content-length':
                    self.send_header(name, value)
        elif status not in {204, 205} and status >= 200:
            self.send_header('Content-Length', str(len(payload)))
        self.send_header('Connection', 'close')
        self.end_headers()
        if self.command != 'HEAD' and status not in {204, 205, 304} and status >= 200:
            self.wfile.write(payload)

    def read_forward_body(self):
        lengths = self.headers.get_all('Content-Length', [])
        encodings = self.headers.get_all('Transfer-Encoding', [])
        if len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings):
            raise ValueError('Ambiguous framing')
        if not encodings:
            text = lengths[0] if lengths else '0'
            if not text.isascii() or not text.isdecimal() or int(text) > MAX_REQUEST:
                raise ValueError('Invalid body length')
            body = self.rfile.read(int(text))
            if len(body) != int(text):
                raise ValueError('Incomplete body')
            return body
        if encodings[0].lower() != 'chunked':
            raise ValueError('Unsupported transfer coding')
        body = bytearray()
        while True:
            line = self.rfile.readline(8193)
            if not line.endswith(b'\r\n') or len(line) > 8192:
                raise ValueError('Invalid chunk header')
            digits = line[:-2].split(b';', 1)[0]
            if not digits or any(c not in b'0123456789abcdefABCDEF' for c in digits):
                raise ValueError('Invalid chunk size')
            size = int(digits, 16)
            if len(body) + size > MAX_REQUEST:
                raise ValueError('Body too large')
            if not size:
                # Trailers are not used by the X17 contract; do not silently discard them.
                if self.rfile.readline(8193) != b'\r\n':
                    raise ValueError('Request trailers unsupported')
                return bytes(body)
            chunk = self.rfile.read(size)
            if len(chunk) != size or self.rfile.read(2) != b'\r\n':
                raise ValueError('Incomplete chunk')
            body.extend(chunk)

    def do_other(self):
        if self.path.startswith('/api/hcamm/'):
            return self.forward_tradingbox()
        return self.reply(404, {'error': 'Unknown endpoint'})

    do_HEAD = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_other

    def do_POST(self):
        if self.path.startswith('/api/hcamm/'):
            return self.forward_tradingbox()
        if not self.server.trusted(self.headers):
            return self.reply(403, {"error": "Local same-origin access required"})
        if self.path not in {"/events", "/capture/events", "/relay/logs", "/logging/events"} and not self.server.authorized(self.headers):
            return self.reply(401, {"error": "Reload the dashboard to start a new local session"})
        try:
            lengths = self.headers.get_all("Content-Length", [])
            length = int(lengths[0]) if len(lengths) == 1 else -1
        except ValueError:
            length = -1
        body_limit = MAX_LOG_BODY if self.path in {"/logging/events"} else MAX_BODY
        if not 0 <= length <= body_limit or self.headers.get("Transfer-Encoding"):
            return self.reply(413, {"error": "Invalid request size"})
        try:
            body = self.rfile.read(length)
            if self.path == '/logging/events':
                token = self.server.bridge_token
                if (self.headers.get('Origin') is not None or not token or not hmac.compare_digest(
                        self.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode())):
                    return self.reply(401, {'error': 'Logging sender authentication required'})
                if len(body) != length:
                    return self.reply(400, {'error': 'Incomplete logging body'})
                result = self.server.controller.logging_events.accept(body, self.headers.get('Content-Type', 'application/octet-stream'))
                raw = self.server.controller.native_store.raw_log
                raw.append('in', 'logging', body.decode('utf-8', errors='replace'), token)
                raw.append('out', 'logging', result, token)
                return self.reply(202, result)
            if self.path == '/relay/logs':
                token = self.server.bridge_token
                if (self.headers.get('Origin') is not None or not token or not hmac.compare_digest(
                        self.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode())):
                    return self.reply(401, {'error': 'Native relay authentication required'})
                payload = json.loads(body)
                result = self.server.controller.relay_logs.accept(payload)
                if not result['duplicate']:
                    raw = base64.b64decode(payload['data_base64']).decode('utf-8', errors='replace')
                    self.server.controller.native_store.raw_log.append('in', 'tradingbox-relay', raw, token)
                return self.reply(202, result)
            if self.path == "/capture/events":
                token = self.server.bridge_token
                if not token or not hmac.compare_digest(
                    self.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()
                ):
                    return self.reply(401, {"error": "Sender authentication required"})
                self.server.controller.native_store.raw_log.append('in', 'http', body.decode('utf-8', errors='replace'), token)
                result = self.server.controller.receive_native(json.loads(body))
                self.server.controller.native_store.raw_log.append('out', 'http', result, token)
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
            if self.path == '/api/tradingbox-forwarding':
                if controller.tradingbox_forwarder is None:
                    raise ValueError('Forwarder unavailable')
                try:
                    result = controller.tradingbox_forwarder.configure(payload)
                except ValueError as exc:
                    return self.reply(400, {'error': str(exc)})
            elif self.path == '/api/broker-profiles/action':
                if controller.broker_profiles is None:
                    raise ValueError('Broker profiles not configured')
                controller.broker_profiles.action(payload.get('profile'), payload.get('action'))
                result = controller.broker_profiles.snapshot()
            elif self.path == "/api/connect":
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
