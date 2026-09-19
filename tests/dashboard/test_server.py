import io
import json
from types import SimpleNamespace

import pytest

from matchtrader.dashboard.controller import DashboardController
from matchtrader.dashboard.server import DashboardHTTPServer, Handler
from matchtrader.dashboard.signals import SignalHub


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


def test_oversized_and_invalid_ingress_rejected_without_authentication(server):
    headers = {"X-Session-Token": "test-session", "Content-Length": "999999"}
    assert call(server, "/api/start", "POST", {}, headers)[0] == 413
    assert call(server, "/events", "POST", {})[0] == 400
    assert call(server, "/capture/events", "POST", {})[0] == 400


def test_native_ingress_acks_matching_id_only_after_durable_capture(server):
    server.controller.start("123")
    payload = {
        "event_id": "qt-event",
        "machine": "qt",
        "connection_id": "source-connection",
        "account_id": "source-account",
        "order_id": "qt-order",
        "kind": "ORDER",
        "emitted_at": "2026-09-09T00:00:00Z",
        "snapshot": True,
    }
    headers = {}
    status, raw = call(server, "/capture/events", "POST", payload, headers)
    result = json.loads(raw)
    assert status == 202 and result["event_id"] == "qt-event" and result["trade_id"]
    status, raw = call(server, "/capture/events", "POST", payload, headers)
    assert status == 202 and json.loads(raw)["duplicate"]
    assert call(server, "/api/capture/events")[0] == 401


def test_token_refresh_requires_session_and_routes_to_relogin(server):
    calls = []
    server.controller.refresh_session = lambda: calls.append(True) or {"token_expires_at": "new-expiry"}
    assert call(server, "/api/token/refresh", "POST", {})[0] == 401
    assert calls == []
    status, body = call(server, "/api/token/refresh", "POST", {}, {"X-Session-Token": "test-session"})
    assert status == 200 and json.loads(body)["token_expires_at"] == "new-expiry"
    assert calls == [True]


def test_http_signal_aliases_require_no_token_or_capture_and_never_dispatch(server, tmp_path):
    hub = SignalHub(tmp_path / "signals.sqlite3")
    server.signal_hub = hub
    server.controller.receive_native = lambda payload: pytest.fail("Signal intake must not dispatch trades")
    try:
        for path in ("/signals?source=R01", "/capture/events", "/events"):
            status, body = call(server, path, "POST", {"event_id": "signal-test", "custom": 42})
            assert status == 202 and json.loads(body)["event_id"] == "signal-test"
        assert len(hub.recent()) == 3
        assert hub.recent()[0]["source"] == "R01"
        assert not server.controller.running and server.controller.api is None
    finally:
        hub.close()


@pytest.mark.parametrize("path", ["/api/hcamm/events", "/signals/api/hcamm/events"])
def test_b21_appended_route_preserves_raw_batch_without_control_auth(server, tmp_path, path):
    hub = SignalHub(tmp_path / "b21.sqlite3")
    server.signal_hub = hub
    server.controller.receive_native = lambda payload: pytest.fail("Must not execute sender batches")
    batch = [{"machineId": "nasdaq_30s", "source": "r01Auto", "kind": "intent",
              "symbol": "BTCUSD", "clientEventId": "b21-test"}]
    try:
        status, body = call(server, path, "POST", batch)
        assert status == 202 and json.loads(body)["status"] == "received"
        assert hub.recent()[0]["payload"] == batch
        assert hub.recent()[0]["raw"] == json.dumps(batch)
        assert call(server, "/api/start", "POST", {})[0] == 401
        assert call(server, path, "POST", batch,
                    {"Host": "attacker.example:8765"})[0] == 403
    finally:
        hub.close()
