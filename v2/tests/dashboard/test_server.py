import io
import json
from types import SimpleNamespace

import pytest

from matchtrader.dashboard.controller import DashboardController
from matchtrader.dashboard.server import DashboardHTTPServer, Handler


class MemorySocket:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = b""

    def settimeout(self, seconds):
        pass

    def makefile(self, *args):
        return self.input

    def sendall(self, body):
        self.output += body


@pytest.fixture
def server(settings, tmp_path):
    assets = tmp_path / "dist"
    assets.mkdir()
    (assets / "index.html").write_text("<html>Dashboard</html>")
    controller = DashboardController(settings, tmp_path / "data")
    server = SimpleNamespace(
        controller=controller,
        assets=assets,
        session_token="test-session",
        bridge_token="event-token" * 4,
        server_port=8765,
    )
    server.trusted = lambda headers: DashboardHTTPServer.trusted(server, headers)
    server.authorized = lambda headers: DashboardHTTPServer.authorized(server, headers)
    yield server
    controller.close()


def call(server, path, method="GET", body=None, headers=None):
    headers = {"Host": "127.0.0.1:8765", **(headers or {})}
    data = json.dumps(body).encode() if body is not None else b""
    if method == "POST":
        headers.setdefault("Content-Length", str(len(data)))
    raw = (
        f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
    ).encode() + data
    sock = MemorySocket(raw)
    Handler(sock, ("127.0.0.1", 5000), server)
    head, response = sock.output.split(b"\r\n\r\n", 1)
    return int(head.split()[1]), response


def test_session_and_assets_same_origin_only(server):
    assert call(server, "/")[0] == 200
    assert call(server, "/api/session")[0] == 200
    assert call(server, "/api/session", headers={"Host": "attacker.example:8765"})[0] == 403
    assert call(server, "/api/session", headers={"Origin": "https://attacker.example"})[0] == 403
    assert call(server, "/api/session", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert call(server, "/../data/private.db")[0] == 404


def test_api_requires_session_and_can_start_stop(server):
    headers = {"X-Session-Token": "test-session"}
    assert call(server, "/api/status")[0] == 401
    assert call(server, "/api/start", "POST", {"account_id": "123"})[0] == 401
    status, body = call(server, "/api/start", "POST", {"account_id": "123"}, headers)
    assert status == 200 and json.loads(body)["running"]
    assert call(server, "/api/events", headers=headers)[0] == 200
    status, body = call(server, "/api/stop", "POST", {}, headers)
    assert status == 200 and not json.loads(body)["running"]
    assert call(server, "/api/start", "POST", [], headers)[0] == 400
    assert call(server, "/api/unknown", headers=headers)[0] == 404


def test_oversized_and_unauthenticated_ingress_rejected(server):
    headers = {"X-Session-Token": "test-session", "Content-Length": "999999"}
    assert call(server, "/api/start", "POST", {}, headers)[0] == 413
    assert call(server, "/events", "POST", {})[0] == 401


def test_token_refresh_requires_session_and_routes_to_relogin(server):
    calls = []
    server.controller.refresh_session = lambda: calls.append(True) or {"token_expires_at": "new-expiry"}
    assert call(server, "/api/token/refresh", "POST", {})[0] == 401
    assert calls == []
    status, body = call(server, "/api/token/refresh", "POST", {}, {"X-Session-Token": "test-session"})
    assert status == 200 and json.loads(body)["token_expires_at"] == "new-expiry"
    assert calls == [True]
