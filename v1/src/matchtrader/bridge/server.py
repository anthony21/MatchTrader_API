"""Authenticated loopback-only shadow ingress, using the Python standard library."""

import hmac
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from pydantic import ValidationError

from .api import ShadowBridge

MAX_BODY = 16384


def ingest(authorization: str, body: bytes, token: str, bridge: ShadowBridge):
    if not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
        return 401, {"error": "unauthorized"}
    if len(body) > MAX_BODY:
        return 413, {"error": "body_too_large"}
    try:
        payload = json.loads(body)
        result = bridge.receive(payload)
    except (ValueError, ValidationError, UnicodeError):
        return 400, {"error": "invalid_order_event"}
    return 202, result  # Local capture only, never broker acceptance.


def serve(bridge: ShadowBridge, token: str, *, port: int = 8765):
    if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError("Set a random bridge token of at least 32 non-whitespace ASCII characters")

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def log_message(self, *args):
            pass  # Do not log authentication headers or caller-controlled content.

        def reply(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        def do_POST(self):
            if self.path != "/events":
                return self.reply(404, {"error": "not_found"})
            try:
                lengths = self.headers.get_all("Content-Length", [])
                length = int(lengths[0]) if len(lengths) == 1 else -1
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY or self.headers.get("Transfer-Encoding"):
                return self.reply(413, {"error": "invalid_body_length"})
            try:
                status, result = ingest(
                    self.headers.get("Authorization", ""), self.rfile.read(length), token, bridge
                )
            except TimeoutError:
                return self.reply(408, {"error": "request_timeout"})
            self.reply(status, result)

    with HTTPServer(("127.0.0.1", port), Handler) as server:
        server.serve_forever(poll_interval=0.5)
