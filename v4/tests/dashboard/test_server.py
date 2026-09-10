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


def test_mapping_endpoint_is_authenticated_and_account_scoped(server):
    assert call(server, '/api/trade-mappings')[0] == 401
    status, body = call(server, '/api/trade-mappings', headers={'X-Session-Token': 'test-session'})
    assert status == 200
    assert json.loads(body) == {'account_id': '123', 'mappings': []}
    _, raw = call(server, '/api/status', headers={'X-Session-Token': 'test-session'})
    assert json.loads(raw)['version'] == '0.6.0'


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
    assert call(server, "/capture/events", "POST", {})[0] == 401


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
    headers = {"Authorization": "Bearer " + server.bridge_token}
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


def test_event_meanings_catalog_requires_authentication(server):
    assert call(server, '/api/event-meanings')[0] == 401
    status, raw = call(server, '/api/event-meanings', headers={'X-Session-Token': 'test-session'})
    assert status == 200
    result = json.loads(raw)
    assert result['version'] == '1.0.0'
    assert result['sources']['R01'] == 'R01 strategy'
    assert {'POSITION', 'FILL', 'LEDGER'} <= {item['code'] for item in result['events']}


def test_native_stream_is_authenticated_and_delivers_committed_changes(settings, tmp_path):
    from datetime import UTC, datetime
    from http.client import HTTPConnection
    from socket import AF_INET, SOCK_STREAM, socket
    from threading import Thread

    from matchtrader.capture.event import CaptureEvent

    controller = DashboardController(settings, tmp_path / 'stream-data')
    actual = DashboardHTTPServer(('127.0.0.1', 0), controller, tmp_path, '')
    worker = Thread(target=actual.serve_forever, daemon=True)
    worker.start()
    client = HTTPConnection('127.0.0.1', actual.server_port, timeout=3)

    def loopback_only(address, timeout, source_address):
        assert address == ('127.0.0.1', actual.server_port)
        connection = socket(AF_INET, SOCK_STREAM)
        connection.settimeout(timeout)
        assert connection.connect_ex(address) == 0
        return connection

    client._create_connection = loopback_only
    try:
        client.request('GET', '/api/capture/stream')
        assert client.getresponse().status == 401
        client.close()
        client.request('GET', '/api/capture/stream', headers={'X-Session-Token': actual.session_token,
                                                           'Origin': 'https://attacker.example'})
        assert client.getresponse().status == 403
        client.close()
        client.request('GET', '/api/capture/stream', headers={'X-Session-Token': actual.session_token})
        response = client.getresponse()
        assert response.status == 200 and response.getheader('Content-Type').startswith('text/event-stream')
        assert json.loads(response.readline().decode().removeprefix('data: '))['events'] == []
        assert response.readline() == b'\n'
        controller.native_store.record(CaptureEvent(event_id='stream-1', machine='test', connection_id='test',
            account_id='source', emitted_at=datetime.now(UTC), kind='POSITION', symbol='EURUSD'))
        pushed = json.loads(response.readline().decode().removeprefix('data: '))
        assert pushed['events'][0]['event_id'] == 'stream-1'
        assert pushed['events'][0]['meaning']['event']['code'] == 'POSITION'
        response.close()
    finally:
        client.close()
        actual.shutdown()
        actual.server_close()
        worker.join(timeout=3)
        controller.close()
