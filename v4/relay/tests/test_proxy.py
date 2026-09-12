import base64
import gzip
import http.client
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transparent_proxy import ProxyServer


@pytest.fixture
def exchange(tmp_path):
    seen = []
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            seen.append((self.command, self.path, list(self.headers.raw_items()), self.rfile.read(int(self.headers.get('Content-Length', 0)))))
            payload = gzip.compress(b'{"unknown": ["cancel", 7], "literal": "unchanged"}', mtime=0)
            self.send_response(302 if self.path.startswith('/redirect') else 403, 'Actual upstream reason')
            self.send_header('Content-Encoding', 'gzip')
            self.send_header('Location', '/do-not-follow')
            self.send_header('Set-Cookie', 'one=1')
            self.send_header('Set-Cookie', 'two=2')
            self.send_header('X-Unknown', 'exact-value')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(payload)
        do_GET = do_HEAD = do_POST
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    proxy = ProxyServer(('127.0.0.1', 0), f'http://127.0.0.1:{upstream.server_port}', tmp_path, forward=True)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (upstream, proxy)]
    for thread in threads:
        thread.start()
    yield proxy, seen, tmp_path
    for server in (proxy, upstream):
        server.shutdown()
        server.server_close()
    for thread in threads:
        thread.join()


@pytest.mark.parametrize('path,status', [('/api/hcamm/events?x=%2F&x=2', 403), ('/redirect', 302)])
def test_preserves_messages_errors_redirects_headers_and_compressed_bytes(exchange, path, status):
    proxy, seen, logs = exchange
    body = b' { "unknown": 123, "signal": "BUY" }\r\n\x00\xff'
    client = http.client.HTTPConnection('127.0.0.1', proxy.server_port)
    client.request('POST', path, body=body, headers={'X-HCAMM-Key': 'fake-test-key', 'X-Unknown': 'unchanged', 'Content-Type': 'application/octet-stream'})
    response = client.getresponse()
    reply = response.read()
    assert response.status == status and response.reason == 'Actual upstream reason'
    assert response.getheader('Location') == '/do-not-follow'
    assert [value for key, value in response.getheaders() if key == 'Set-Cookie'] == ['one=1', 'two=2']
    assert len(seen) == 1
    assert seen[0][:2] == ('POST', path) and seen[0][3] == body
    received = dict(seen[0][2])
    assert received['X-HCAMM-Key'] == 'fake-test-key' and received['X-Unknown'] == 'unchanged'
    assert 'User-Agent' not in received
    request_record = json.loads(next(logs.glob('raw-request-*')).read_text())
    response_record = json.loads(next(logs.glob('raw-response-*')).read_text())
    assert request_record['request_id'] == response_record['request_id']
    assert base64.b64decode(request_record['body_base64']) == body
    assert base64.b64decode(response_record['body_base64']) == reply
    assert gzip.decompress(reply).startswith(b'{"unknown"')
    assert 'fake-test-key' not in json.dumps(request_record)
    client.close()


def test_chunked_request_and_head(exchange):
    proxy, seen, _ = exchange
    client = http.client.HTTPConnection('127.0.0.1', proxy.server_port)
    client.request('POST', '/api/hcamm/events', body=iter([b'first', b'\x00second']), encode_chunked=True)
    assert client.getresponse().read()
    assert seen[0][3] == b'first\x00second'
    client.close()
    client = http.client.HTTPConnection('127.0.0.1', proxy.server_port)
    client.request('HEAD', '/head')
    response = client.getresponse()
    assert response.read() == b'' and int(response.getheader('Content-Length')) > 0
    client.close()


def test_archive_failure_does_not_replace_received_upstream_response(exchange, monkeypatch):
    proxy, _, _ = exchange
    original = proxy.record
    def record(direction, row):
        if direction == 'response':
            raise OSError('simulated disk failure')
        original(direction, row)
    monkeypatch.setattr(proxy, 'record', record)
    client = http.client.HTTPConnection('127.0.0.1', proxy.server_port)
    client.request('GET', '/failure')
    response = client.getresponse()
    assert response.status == 403 and response.read()
    client.close()


def test_local_mode_never_contacts_configured_upstream(exchange, monkeypatch):
    proxy, seen, logs = exchange
    proxy.forward = False
    client = http.client.HTTPConnection('127.0.0.1', proxy.server_port)
    client.request('GET', '/api/hcamm/commands')
    response = client.getresponse()
    body = json.loads(response.read())
    assert response.status == 200 and body['origin'] == 'x.0.1'
    assert body['forwarded_to_tradingbox'] is False and seen == []
    client.close()
    record = json.loads(next(logs.glob('raw-response-*')).read_text())
    assert record['origin'] == 'x.0.1'


def test_relay_cli_refuses_forwarding_to_a_non_https_origin(tmp_path):
    import subprocess
    config = tmp_path / 'relay.json'
    config.write_text('{"forward":true}')
    env = tmp_path / 'test.env'
    env.write_text('MTR_BRIDGE_TOKEN=local-test-key-with-32-characters-long')
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'tb-relay.py'), '--config', str(config), '--env', str(env)], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Forwarding requires an https upstream origin' in result.stderr
