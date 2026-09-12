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
    assert call(server, "/api/raw/stream")[0] == 401
    assert call(server, "/api/raw/stream", headers={"Origin": "https://attacker.example"})[0] == 403
    assert call(server, "/")[0] == 200
    assert call(server, "/api/session")[0] == 200
    assert call(server, "/api/session", headers={"Host": "attacker.example:8765"})[0] == 403
    assert call(server, "/api/session", headers={"Origin": "https://attacker.example"})[0] == 403
    assert call(server, "/api/session", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert call(server, "/../data/private.db")[0] == 404


def test_relay_ingress_is_durable_authenticated_and_never_routes_trades(server):
    from tests.capture.test_relay_store import envelope

    payload = envelope(b'{"kind":"ACCEPTED","action":"CREATE","unknown":true}\n')
    assert call(server, '/relay/logs', 'POST', payload)[0] == 401
    headers = {'Authorization': 'Bearer ' + server.bridge_token}
    assert call(server, '/relay/logs', 'POST', payload, {**headers, 'Origin': 'http://127.0.0.1:8765'})[0] == 401
    status, body = call(server, '/relay/logs', 'POST', payload, headers)
    assert status == 202 and json.loads(body)['durable']
    status, body = call(server, '/relay/logs', 'POST', payload, headers)
    assert status == 202 and json.loads(body)['duplicate']
    assert server.controller.native_store.db.execute('SELECT count(*) FROM events').fetchone()[0] == 0
    assert not server.controller.native.armed
    assert call(server, '/api/relay/logs')[0] == 401
    status, body = call(server, '/api/relay/logs', headers={'X-Session-Token': 'test-session'})
    assert status == 200 and len(json.loads(body)['records']) == 1


def test_mapping_endpoint_is_authenticated_and_account_scoped(server):
    assert call(server, '/api/trade-mappings')[0] == 401
    status, body = call(server, '/api/trade-mappings', headers={'X-Session-Token': 'test-session'})
    assert status == 200
    assert json.loads(body) == {'account_id': '123', 'mappings': []}
    _, raw = call(server, '/api/status', headers={'X-Session-Token': 'test-session'})
    assert json.loads(raw)['version'] == '0.9.1'


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


def test_logging_is_opaque_authenticated_and_never_routes(server, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('Logging must not route')
    monkeypatch.setattr(server.controller, 'receive_native', forbidden)
    body = {'kind': 'ACCEPTED', 'action': 'CREATE', 'source': 'X17', 'custom': [1, 2]}
    assert call(server, '/logging/events', 'POST', body)[0] == 401
    headers = {'Authorization': 'Bearer ' + server.bridge_token}
    status, response = call(server, '/logging/events', 'POST', body, headers)
    ack = json.loads(response)
    assert status == 202 and ack['durable'] and not ack['executed'] and not ack['forwarded']
    assert not server.controller.running
    status, page = call(server, '/api/logging/events', headers={'X-Session-Token': 'test-session'})
    row = json.loads(page)['records'][0]
    assert status == 200 and row['receipt_id'] == ack['receipt_id']
    assert 'data_base64' not in row and 'custom' in row['preview']
    assert call(server, '/api/logging/events')[0] == 401
    assert call(server, '/api/logging/events?before=-1', headers={'X-Session-Token': 'test-session'})[0] == 400


def test_broker_profile_actions_require_session_and_known_profile(server):
    from matchtrader.dashboard.broker_profiles import BrokerProfiles
    server.controller.broker_profiles = BrokerProfiles({'MTR': server.controller.settings}, server.controller)
    assert call(server, '/api/broker-profiles')[0] == 401
    assert call(server, '/api/broker-profiles/action', 'POST', {'profile': 'MTR', 'action': 'connect'})[0] == 401
    headers = {'X-Session-Token': 'test-session'}
    status, body = call(server, '/api/broker-profiles', headers=headers)
    assert status == 200 and json.loads(body)['profiles'][0]['profile'] == 'MTR'
    assert call(server, '/api/broker-profiles/action', 'POST', {'profile': 'missing', 'action': 'refresh'}, headers)[0] == 400
    assert call(server, '/api/broker-profiles/action', 'POST', {'profile': 'MTR', 'action': 'trade'}, headers)[0] == 400


def test_profile_login_and_selection_require_session_and_forward_account_id(server):
    calls = []
    server.controller.broker_profiles = SimpleNamespace(
        action=lambda *args: calls.append(args), snapshot=lambda: {'profiles': []}, close=lambda: None)
    for action in ['login', 'select']:
        payload = {'profile': 'GTR', 'action': action, 'account_id': '222'}
        assert call(server, '/api/broker-profiles/action', 'POST', payload)[0] == 401
        assert not calls
        assert call(server, '/api/broker-profiles/action', 'POST', payload,
                    {'X-Session-Token': 'test-session'})[0] == 200
        assert calls.pop() == ('GTR', action, '222')


def test_tradingbox_gate_is_authenticated_and_separate_from_copying(server, tmp_path):
    from matchtrader.capture.tradingbox_forwarder import TradingBoxForwarder
    calls = []
    def upstream(url, headers, body, **kwargs):
        calls.append(body)
        return 201, 'Created', [('Content-Type', 'application/json')], b'{"upstream":"accepted"}'
    f = TradingBoxForwarder(tmp_path / 'forward.json', server.controller.logging_events, server.controller.native_store.raw_log, api_key='test-tb-key', send=upstream)
    server.controller.tradingbox_forwarder = f
    config = {'url': 'https://tradingbox.pro/api/hcamm/events', 'enabled': True, 'live': True}
    assert call(server, '/api/tradingbox-forwarding', 'POST', config)[0] == 401
    assert call(server, '/api/tradingbox-forwarding', headers={'X-Session-Token': 'test-session'})[0] == 200
    assert call(server, '/api/hcamm/events', 'POST', {'intent': 1})[0] == 401
    headers = {'X-HCAMM-Key': 'test-tb-key'}
    assert call(server, '/api/hcamm/events', 'POST', {'intent': 1}, headers)[0] == 202
    assert calls == []
    assert call(server, '/api/tradingbox-forwarding', 'POST', config, {'X-Session-Token': 'test-session'})[0] == 200
    status, response = call(server, '/api/hcamm/events', 'POST', {'intent': 2}, headers)
    assert status == 201 and json.loads(response)['upstream'] == 'accepted'
    assert len(calls) == 1 and not server.controller.native.armed
    assert not server.controller.running
    assert call(server, '/api/hcamm/events', 'POST', {}, {**headers, 'Origin': 'http://127.0.0.1:8765'})[0] == 401
    assert server.controller.native_store.db.execute('SELECT count(*) FROM events').fetchone()[0] == 0


@pytest.mark.parametrize('method', ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'])
def test_tradingbox_methods_queries_and_real_replies(server, tmp_path, method):
    from matchtrader.capture.tradingbox_forwarder import TradingBoxForwarder
    sent = []
    def upstream(url, headers, body, *, method):
        sent.append((method, url, headers, body))
        return 200, 'OK', [('Content-Type', 'application/json'), ('X-Request-Id', 'tb-123'),
                           ('Set-Cookie', 'one=1'), ('Set-Cookie', 'two=2'),
                           ('Content-Length', '27')], b'{"commands":[{"id":"cmd1"}]}'
    f = TradingBoxForwarder(tmp_path / 'f.json', server.controller.logging_events,
        server.controller.native_store.raw_log, api_key='fake-key', send=upstream)
    server.controller.tradingbox_forwarder = f
    f.configure({'url': 'https://tradingbox.org/api/hcamm/events', 'enabled': True, 'live': True})
    target = '/api/hcamm/commands?machineId=X17%20A&cursor=1&cursor=2&key=private'
    body = b'{ "eventId": "original", "unknown": 0.05 }'
    raw = (f'{method} {target} HTTP/1.1\r\nHost: localhost:8765\r\n'
           f'X-HCAMM-Key: fake-key\r\nUser-Agent: Original-X17\r\nContent-Length: {len(body)}\r\n\r\n').encode() + body
    sock = MemorySocket(raw)
    Handler(sock, ('127.0.0.1', 1), server)
    head, reply = sock.output.split(b'\r\n\r\n', 1)
    assert b'200 OK' in head and b'X-Request-Id: tb-123' in head
    assert head.count(b'Set-Cookie:') == 2 and b'Server:' not in head
    assert reply == (b'' if method == 'HEAD' else b'{"commands":[{"id":"cmd1"}]}')
    assert sent[0][:2] == (method, 'https://tradingbox.org' + target)
    assert sent[0][3] == body and ('User-Agent', 'Original-X17') in sent[0][2]
    rows = f.store.feed()['records']
    assert rows[0]['metadata']['cycle_id'] == rows[1]['metadata']['cycle_id']
    assert rows[1]['metadata']['method'] == method
    assert rows[1]['metadata']['path'] == '/api/hcamm/commands'
    assert 'private' not in json.dumps(rows)
    assert call(server, target, method)[0] == 401
    f.configure({'url': f.url, 'enabled': False, 'live': False})
    assert call(server, target, method, headers={'X-HCAMM-Key': 'fake-key'})[0] == 202
    assert len(sent) == 1


def test_tradingbox_chunked_payload_and_ambiguous_framing(server, tmp_path):
    from matchtrader.capture.tradingbox_forwarder import TradingBoxForwarder
    sent = []
    def upstream(url, headers, body, **kwargs):
        sent.append(body)
        return 204, 'No Content', [], b''
    f = TradingBoxForwarder(tmp_path / 'f.json', server.controller.logging_events,
        server.controller.native_store.raw_log, api_key='fake-key', send=upstream)
    server.controller.tradingbox_forwarder = f
    f.configure({'url': 'https://tradingbox.pro/api/hcamm/events', 'enabled': True, 'live': True})
    base = b'POST /api/hcamm/events HTTP/1.1\r\nHost: localhost:8765\r\nX-HCAMM-Key: fake-key\r\n'
    def exchange(framing, body):
        sock = MemorySocket(base + framing + b'\r\n' + body)
        Handler(sock, ('127.0.0.1', 1), server)
        return sock.output
    reply = exchange(b'Transfer-Encoding: chunked\r\n', b'3\r\nabc\r\n2;test=1\r\n\x00z\r\n0\r\n\r\n')
    assert b'204 No Content' in reply and b'Content-Length:' not in reply
    assert sent == [b'abc\x00z']
    for headers, body in [
        (b'Content-Length: 1\r\nTransfer-Encoding: chunked\r\n', b'a'),
        (b'Content-Length: 1\r\nContent-Length: 1\r\n', b'a'),
        (b'Transfer-Encoding: chunked\r\n', b'100001\r\n'),
        (b'Transfer-Encoding: chunked\r\n', b'1\r\n'),
        (b'Content-Length: 1048577\r\n', b''),
    ]:
        assert b'400 Bad Request' in exchange(headers, body)
    assert len(sent) == 1


def test_closed_history_is_authenticated_and_account_scoped(server):
    from tests.dashboard.test_closed_history import WINDOW, broker, trade
    fake = broker([trade()])
    fake.close = lambda: None
    server.controller.api = fake
    server.controller.selected = '123'
    payload = {**WINDOW, 'account_id': '123'}
    assert call(server, '/api/orders/closed', 'POST', payload)[0] == 401
    headers = {'X-Session-Token': 'test-session'}
    code, raw = call(server, '/api/orders/closed', 'POST', payload, headers)
    assert code == 200 and json.loads(raw)['summary']['closed'] == 1
    assert call(server, '/api/orders/closed', 'POST', {**payload, 'account_id': 'other'}, headers)[0] == 400
    assert call(server, '/api/orders/closed', 'POST', payload, {**headers, 'Origin': 'https://attacker.example'})[0] == 403


def test_p01_observations_join_display_feed_without_entering_native_journal(server):
    store = server.controller.native_store
    before = store.db.execute('SELECT count(*) FROM events').fetchone()[0]
    server.controller.p01_log.record("2026-09-11T17:28:10Z box OPEN clicked id='P01RR_172810_193' side=0 entry=76702.2055")
    status, raw = call(server, '/api/capture/events', headers={'X-Session-Token': 'test-session'})
    assert status == 200
    event = json.loads(raw)['events'][-1]
    assert event['kind'] == 'P01_LOG' and event['trade_id'] == 'P01RR_172810_193'
    assert store.db.execute('SELECT count(*) FROM events').fetchone()[0] == before
    assert not server.controller.native.armed


def test_large_signal_batch_is_authenticated_and_logged_with_copying_off(server):
    from tests.dashboard.test_signal_copy import packet

    batch = [packet(clientEventId=f'large-{i}', label='x' * 200,
                    kind='intent' if i % 2 else 'closed') for i in range(46)]
    assert len(json.dumps(batch).encode()) > 16384
    headers = {'Authorization': 'Bearer ' + server.bridge_token}
    assert call(server, '/capture/signals', 'POST', batch)[0] == 401
    status, raw = call(server, '/capture/signals', 'POST', batch, headers)
    assert status == 202
    assert len(json.loads(raw)['results']) == 46
    assert not server.controller.signal_copy.armed
    assert server.controller.signal_copy.db.execute('SELECT count(*) FROM signals').fetchone()[0] == 46
    assert call(server, '/capture/signals', 'POST', 'x' * (1024 * 1024), headers)[0] == 413
    assert call(server, '/capture/signals', 'POST', batch,
                {**headers, 'Origin': 'http://127.0.0.1:8765'})[0] == 401
    assert call(server, '/api/start', 'POST', batch,
                {'X-Session-Token': 'test-session'})[0] == 413


def test_disarmed_signal_is_captured_and_no_broker_call_occurs(server):
    from tests.dashboard.test_signal_copy import packet

    class Forbidden:
        connection = SimpleNamespace(session_expires_at=None, account_id='123')

        def __getattr__(self, name):
            raise AssertionError(f'Broker call {name} attempted while signal copying is off')

    server.controller.api = Forbidden()
    server.controller.connection = 'connected'
    headers = {'Authorization': 'Bearer ' + server.bridge_token}
    status, raw = call(server, '/capture/signals', 'POST', [packet()], headers)
    result = json.loads(raw)
    assert status == 202 and result['forwarded_to_tradingbox'] is False
    assert result['results'][0]['status'] == 'held' and 'off' in result['results'][0]['reason']
    status, raw = call(server, '/api/signal-copy-events', headers={'X-Session-Token': 'test-session'})
    assert status == 200 and json.loads(raw)['events'][0]['clientEventId'] == 'event-one'
    assert call(server, '/api/signal-copy-events')[0] == 401
    server.controller.api = None


def test_shutdown_is_session_authenticated_and_explicit(server):
    from threading import Event
    stopped = Event()
    server.shutdown = stopped.set
    headers = {'X-Session-Token': 'test-session'}
    assert call(server, '/api/shutdown', 'POST', {})[0] == 401
    assert not stopped.is_set()
    assert call(server, '/api/shutdown', 'POST', {}, headers)[0] == 200
    assert stopped.wait(1)
    assert not server.controller.running


def test_signal_copy_routes_are_authenticated_and_archive_is_never_an_execution_source(server):
    from tests.capture.test_relay_store import envelope
    from tests.dashboard.test_signal_copy import Broker, config, packet
    headers = {'X-Session-Token': 'test-session'}
    assert call(server, '/api/signal-copy-settings')[0] == 401
    assert call(server, '/capture/signals', 'POST', [packet()])[0] == 401
    controller = server.controller
    controller.interactive_copying = True
    broker = Broker()
    broker.close = lambda: None
    controller.api = broker
    controller.connection = 'connected'
    controller.native.demo_verified = False
    broker.connection = SimpleNamespace(account_id=controller.selected)
    settings = config(destination_account=controller.selected)
    assert call(server, '/api/signal-copy-settings', 'POST', settings, headers)[0] == 200
    assert not controller.signal_copy.armed
    status, raw = call(server, '/api/signal-copy-settings', headers=headers)
    assert status == 200 and json.loads(raw)['live'] is False
    assert call(server, '/api/signal-copying', 'POST', {'enabled': True}, headers)[0] == 200
    assert controller.signal_copy.armed
    relay_headers = {'Authorization': 'Bearer ' + server.bridge_token}
    assert call(server, '/relay/logs', 'POST', envelope(), relay_headers)[0] == 202
    assert not broker.calls
    signal = packet()
    status, body = call(server, '/capture/signals', 'POST', [signal], relay_headers)
    assert status == 202 and json.loads(body)['results'][0]['status'] == 'accepted'
    assert len(broker.calls) == 1
    assert controller.api is broker  # Copying reuses the existing authenticated owner.
    status, body = call(server, '/capture/signals', 'POST', [signal], relay_headers)
    assert json.loads(body)['results'][0]['duplicate'] and len(broker.calls) == 1
    assert call(server, '/capture/signals', 'POST', [packet()], {**relay_headers, 'Origin': 'http://127.0.0.1:8765'})[0] == 401
    assert call(server, '/api/stop', 'POST', {}, headers)[0] == 200
    assert not controller.signal_copy.armed


def test_capture_start_route_is_authenticated_and_ignores_destination_selection(server):
    assert call(server, '/api/capture/start', 'POST', {})[0] == 401
    before = server.controller.selected
    code, _ = call(server, '/api/capture/start', 'POST', {'account_id': 'unrelated'}, {'X-Session-Token': 'test-session'})
    assert code == 200 and server.controller.running
    assert server.controller.selected == before and server.controller.api is None


def test_dashboard_stream_needs_a_session_before_it_streams(server):
    assert call(server, "/api/stream")[0] == 401
    assert call(server, "/api/stream", headers={"Origin": "https://attacker.example"})[0] == 403


def test_dashboard_sections_cover_every_panel_the_shell_used_to_poll(server):
    sections = Handler.dashboard_sections(server.controller, [])
    assert set(sections) == {"status", "events", "capture_events", "mappings", "broker_profiles"}
    assert sections["status"]["version"] and "account_id" in sections["mappings"]
    assert isinstance(sections["capture_events"]["events"], list)
    assert sections["broker_profiles"] == {"profiles": [], "limit": 5}


def test_status_digest_ignores_only_the_advancing_clock(server):
    first = Handler.dashboard_sections(server.controller, [])["status"]
    second = {**first, "server_time": "2099-01-01T00:00:00+00:00"}
    assert Handler.section_digest("status", first) == Handler.section_digest("status", second)
    assert Handler.section_digest("status", {**first, "running": not first["running"]}) \
        != Handler.section_digest("status", first)


def test_section_digests_are_stable_across_two_builds_without_new_evidence(server):
    first = Handler.dashboard_sections(server.controller, [])
    second = Handler.dashboard_sections(server.controller, [])
    assert first["status"]["server_time"] != "" and set(first) == set(second)
    for name in first:
        assert Handler.section_digest(name, first[name]) == Handler.section_digest(name, second[name]), name


def test_every_action_wakes_the_stream_so_the_shell_never_polls(server):
    headers = {"X-Session-Token": "test-session"}
    before = server.controller.native_store.revision
    assert call(server, "/api/capture/start", "POST", {}, headers)[0] == 200
    assert server.controller.native_store.revision > before


def test_dashboard_stream_pushes_only_changed_sections(settings, tmp_path):
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

    def frame(response):
        line = response.readline()
        assert response.readline() == b'\n'
        return line

    try:
        client.request('GET', '/api/stream')
        assert client.getresponse().status == 401
        client.close()
        client.request('GET', '/api/stream', headers={'X-Session-Token': actual.session_token})
        response = client.getresponse()
        assert response.status == 200 and response.getheader('Content-Type').startswith('text/event-stream')
        first = json.loads(frame(response).decode().removeprefix('data: '))
        assert set(first) == {'revision', 'status', 'events', 'capture_events', 'mappings', 'broker_profiles'}
        assert isinstance(first['revision'], int) and first['status']['signal_copying'] is False
        # A wake without new evidence only heartbeats: server_time alone never forces a resend.
        controller.native_store.notify_stream()
        assert frame(response) == b': heartbeat\n'
        controller.native_store.record(CaptureEvent(event_id='stream-1', machine='test', connection_id='test',
            account_id='source', emitted_at=datetime.now(UTC), kind='POSITION', symbol='EURUSD'))
        pushed = json.loads(frame(response).decode().removeprefix('data: '))
        assert pushed['revision'] > first['revision']
        assert pushed['capture_events']['events'][0]['event_id'] == 'stream-1'
        assert 'broker_profiles' not in pushed and 'events' not in pushed
        response.close()
    finally:
        client.close()
        actual.shutdown()
        actual.server_close()
        worker.join(timeout=3)
        controller.close()
