import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from matchtrader.capture.logging_store import LoggingStore
from matchtrader.capture.raw_log import RawLog
from matchtrader.capture.tradingbox_forwarder import TradingBoxForwarder, send_once, validate_url

URL = 'https://tradingbox.pro/api/hcamm/events'
KEY = 'fake-tradingbox-key'


@pytest.fixture
def forwarder(tmp_path):
    store = LoggingStore(tmp_path / 'logs')
    sent = []
    def send(url, headers, body, **kwargs):
        sent.append((url, headers, body))
        return 422, 'Rejected', [('Content-Type', 'application/json')], b'{"decision":"skipped"}'
    value = TradingBoxForwarder(tmp_path / 'forwarding.json', store, RawLog(), api_key=KEY, send=send)
    value.configure({'url': URL, 'enabled': False, 'live': False})
    yield value, sent
    value.close()
    store.close()


def test_off_preview_live_and_restart_do_not_replay(forwarder):
    value, sent = forwarder
    headers = [('X-HCAMM-Key', KEY), ('Content-Type', 'application/json')]
    body = b'{ "unknownIntent": "X17", "price":4300.00 }'
    assert value.authorized(headers)
    assert not value.authorized([*headers, ('x-hcamm-key', KEY)])
    assert not value.authorized([('X-HCAMM-Key', 'wrong')])
    for enabled, live in [(False, False), (True, False)]:
        value.configure({'url': URL, 'enabled': enabled, 'live': live})
        assert value.receive(headers, body, value.ticket())[0] == 202
    assert sent == []
    old = value.ticket()
    value.configure({'url': URL, 'enabled': True, 'live': True})
    assert value.receive(headers, body, old)[0] == 202
    status, _, _, response = value.receive(headers, body, value.ticket())
    assert status == 422 and response == b'{"decision":"skipped"}'
    assert sent == [(URL, headers, body)]
    rows = value.store.feed()['records']
    assert rows[0]['metadata']['cycle_id'] == rows[1]['metadata']['cycle_id']
    assert rows[0]['metadata']['upstream_status'] == 422
    assert json.loads(value.path.read_text()) == {'url': URL}
    restarted = TradingBoxForwarder(value.path, value.store, RawLog(), api_key=KEY)
    assert not restarted.status()['live'] and not restarted.status()['enabled']


def test_uncertain_send_is_not_retried_and_request_log_failure_aborts(forwarder, monkeypatch):
    value, sent = forwarder
    value.configure({'url': URL, 'enabled': True, 'live': True})
    def unavailable(*args, **kwargs):
        sent.append('attempt')
        raise OSError('secret upstream exception')
    value.send = unavailable
    status, _, _, response = value.receive([], b'opaque', value.ticket())
    assert status == 502 and json.loads(response)['status'] == 'uncertain'
    assert sent == ['attempt'] and b'secret' not in response
    def disk_full(*args, **kwargs): raise OSError('disk full')
    monkeypatch.setattr(value.store, 'accept', disk_full)
    with pytest.raises(OSError):
        value.receive([], b'next', value.ticket())
    assert sent == ['attempt']


def test_response_logging_failure_preserves_reply(forwarder, monkeypatch):
    value, sent = forwarder
    value.configure({'url': URL, 'enabled': True, 'live': True})
    original = value._record
    def record(direction, *args, **kwargs):
        if direction == 'out':
            raise OSError('disk full')
        return original(direction, *args, **kwargs)
    monkeypatch.setattr(value, '_record', record)
    assert value.receive([], b'signal', value.ticket())[0] == 422
    assert value.status()['last_result']['response_log_failed']
    assert len(sent) == 1


def test_off_during_inflight_stops_new_requests_without_waiting(forwarder):
    value, sent = forwarder
    entered, finish = Event(), Event()
    def send(*args, **kwargs):
        sent.append(args)
        entered.set()
        assert finish.wait(3)
        return 200, 'OK', [], b'ok'
    value.send = send
    value.configure({'url': URL, 'enabled': True, 'live': True})
    with ThreadPoolExecutor(1) as pool:
        task = pool.submit(value.receive, [], b'first', value.ticket())
        assert entered.wait(3)
        value.configure({'url': URL, 'enabled': False, 'live': False})
        assert value.status()['in_flight'] == 1
        assert value.receive([], b'second', value.ticket())[0] == 202
        finish.set()
        assert task.result()[0] == 200
    assert len(sent) == 1


@pytest.mark.parametrize('url', ['http://tradingbox.pro/api/hcamm/events', 'https://evil.example/api/hcamm/events', 'https://tradingbox.pro/other', 'https://user:pass@tradingbox.pro/api/hcamm/events', URL + '?key=secret'])
def test_invalid_destination(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize('method', ['POST', 'GET', 'HEAD'])
def test_raw_http_transport_preserves_bytes_and_strips_hop_headers(monkeypatch, method):
    from matchtrader.capture import tradingbox_forwarder as module
    seen = []
    class Response:
        status, reason = 307, 'Redirect'
        def read(self, limit): return b'\x1f\x8bcompressed'
        def getheaders(self): return [('Location', 'https://other.example'), ('Set-Cookie', 'a=1'), ('Set-Cookie', 'b=2'), ('Connection', 'close')]
    class Connection:
        def __init__(self, host, timeout): seen.append(('host', host))
        def putrequest(self, method, path, **kwargs): seen.append((method, path))
        def putheader(self, name, value): seen.append((name, value))
        def endheaders(self, body): seen.append(('body', body))
        def getresponse(self): return Response()
        def close(self): seen.append(('closed', True))
    monkeypatch.setattr(module.http.client, 'HTTPSConnection', Connection)
    status, _, headers, body = send_once(URL + '?cursor=a%2Fb&cursor=2', [('Host', 'localhost'), ('X-HCAMM-Key', KEY), ('Connection', 'x-private-hop'), ('x-private-hop', 'omit')], b'\x00original', method=method)
    assert (method, '/api/hcamm/events?cursor=a%2Fb&cursor=2') in seen
    assert status == 307 and body == b'\x1f\x8bcompressed'
    assert ('body', b'\x00original') in seen and ('X-HCAMM-Key', KEY) in seen
    assert ('Host', 'localhost') not in seen and ('x-private-hop', 'omit') not in seen
    assert len([h for h in headers if h[0] == 'Set-Cookie']) == 2


def test_live_requires_key_and_off_controls_are_not_persisted(tmp_path):
    store = LoggingStore(tmp_path / 'logs')
    f = TradingBoxForwarder(tmp_path / 'settings.json', store, RawLog())
    with pytest.raises(ValueError):
        f.configure({'url': URL, 'enabled': True, 'live': True})
    with pytest.raises(ValueError):
        f.configure({'url': URL, 'enabled': 'yes', 'live': False})
    f.configure({'url': URL, 'enabled': True, 'live': False})
    with pytest.raises(ValueError):
        f.configure({'url': 'https://tradingbox.org/api/hcamm/events', 'enabled': True, 'live': False})
    f.configure({'url': URL, 'enabled': False, 'live': False})
    f.configure({'url': '', 'enabled': False, 'live': False})
    assert TradingBoxForwarder(f.path, store, RawLog()).status()['url'] == ''
    f.close()
    store.close()


@pytest.mark.parametrize('target', ['/api/hcamm/../session', '/api/hcamm/%2e%2e/session',
    '//evil.example/api/hcamm/events', 'https://evil.example/api/hcamm/events',
    '/api/hcamm/events#fragment', '/api/hcamm/events?x=bad\r\nHeader:yes'])
def test_proxy_target_cannot_escape_namespace(forwarder, target):
    value, sent = forwarder
    with pytest.raises(ValueError):
        value.receive([], b'', value.ticket(), method='GET', target=target)
    assert not sent


def test_large_body_is_forwarded_whole_with_explicit_archive_truncation(forwarder):
    value, sent = forwarder
    value.configure({'url': URL, 'enabled': True, 'live': True})
    body = b'x' * 100000
    assert value.receive([], body, value.ticket())[0] == 422
    assert sent[0][2] == body
    row = value.store.feed()['records'][1]
    assert row['metadata']['body_truncated'] and row['metadata']['body_bytes_original'] == len(body)
    assert row['body_bytes'] == 65536
