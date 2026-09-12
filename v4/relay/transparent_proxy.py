"""x.0.1: HTTP message proxy with a durable, correlated request/response journal.

Payload bytes and end-to-end headers are preserved. TLS, Host, Connection and
transfer framing necessarily belong to each connection. No redirects or retries.
"""
import base64
import http.client
import json
import os
import ssl
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade'}
SECRET = {'authorization', 'proxy-authorization', 'cookie', 'set-cookie',
          'x-hcamm-key', 'x-api-key', 'api-key'}


def now():
    return datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def connection_fields(headers):
    names = set(HOP)
    for key, value in headers:
        if key.lower() == 'connection':
            names.update(part.strip().lower() for part in value.split(','))
    return names


def logged_headers(headers):
    return [[key, '[redacted]' if key.lower() in SECRET else value] for key, value in headers]


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, address, upstream, logs, *, forward=False, receiver_port=8765, receiver_token=""):
        url = urlsplit(upstream)
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}:
            raise ValueError('Upstream must be an HTTP(S) origin')
        self.forward = forward
        self.receiver_port = receiver_port
        self.receiver_token = receiver_token
        self.upstream = url
        self.logs = Path(logs)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.log_lock = threading.Lock()
        super().__init__(address, ProxyHandler)

    def record(self, direction, record):
        path = self.logs / f'raw-{direction}-{datetime.now(UTC):%Y%m%d}.jsonl'
        data = (json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
        with self.log_lock, path.open('ab') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def read_body(self):
        lengths = self.headers.get_all('Content-Length', [])
        encoding = self.headers.get('Transfer-Encoding', '')
        if (encoding and lengths) or len(lengths) > 1:
            raise ValueError('Ambiguous request framing')
        if encoding:
            if encoding.lower() != 'chunked':
                raise ValueError('Unsupported transfer framing')
            body = bytearray()
            while True:
                line = self.rfile.readline(8192)
                size = int(line.split(b';', 1)[0].strip(), 16)
                if size < 0:
                    raise ValueError('Invalid chunk size')
                if size == 0:
                    trailers = []
                    while True:
                        line = self.rfile.readline(8192)
                        if line == b'\r\n':
                            break
                        if not line:
                            raise ValueError('Incomplete chunk trailers')
                        key, value = line.decode('latin-1').split(':', 1)
                        trailers.append((key.strip(), value.strip()))
                    return bytes(body), trailers
                part = self.rfile.read(size)
                if len(part) != size or self.rfile.read(2) != b'\r\n':
                    raise ValueError('Incomplete request chunk')
                body.extend(part)
        size = int(lengths[0]) if lengths else 0
        if size < 0:
            raise ValueError('Invalid content length')
        body = self.rfile.read(size)
        if len(body) != size:
            raise ValueError('Incomplete request body')
        return body, []

    def _handle(self):
        cycle = str(uuid4())
        started = time.monotonic()
        requested_at = now()
        self.close_connection = True
        try:
            if not self.path.startswith('/') or self.path.startswith('//'):
                raise ValueError('Origin-form target required')
            body, trailers = self.read_body()
            headers = list(self.headers.raw_items())
            # Request trailers are end-to-end fields; promote them without changing values.
            if any(key.lower() in HOP | {'host', 'content-length', 'authorization'} for key, _ in trailers):
                raise ValueError('Invalid request trailer')
            headers += trailers
            self.server.record('request', {'version': 'x.0.1', 'request_id': cycle, 'ts': requested_at,
                                           'method': self.command, 'path': self.path,
                                           'headers': logged_headers(headers), 'body_bytes': len(body),
                                           'body_base64': base64.b64encode(body).decode('ascii')})
        except (ValueError, OSError) as error:
            self.send_error(400 if isinstance(error, ValueError) else 503, 'Request could not be recorded')
            return

        if not self.server.forward:
            return self.local_reply(cycle, started, body)

        connection = None
        try:
            origin = self.server.upstream
            if origin.scheme == 'https':
                connection = http.client.HTTPSConnection(origin.hostname, origin.port, timeout=30, context=ssl.create_default_context())
            else:
                connection = http.client.HTTPConnection(origin.hostname, origin.port, timeout=30)
            connection.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            excluded = connection_fields(headers) | {'host', 'content-length', 'expect'}
            connection.putheader('Host', origin.netloc)
            for key, value in headers:
                if key.lower() not in excluded:
                    connection.putheader(key, value)
            if body or self.headers.get('Content-Length') is not None or self.headers.get('Transfer-Encoding'):
                connection.putheader('Content-Length', str(len(body)))
            connection.putheader('Connection', 'close')
            connection.endheaders(body if body else None)
            response = connection.getresponse()
            response_headers = response.getheaders()
            response_body = response.read()  # Decodes transfer framing only; never content encoding.
            response_record = {'version': 'x.0.1', 'request_id': cycle, 'ts': now(), 'origin': 'TradingBox',
                               'method': self.command, 'path': self.path, 'status': response.status,
                               'reason': response.reason, 'headers': logged_headers(response_headers),
                               'duration_ms': round((time.monotonic() - started) * 1000, 3),
                               'body_bytes': len(response_body), 'body_base64': base64.b64encode(response_body).decode('ascii')}
        except (OSError, http.client.HTTPException) as error:
            # This is an intermediary failure, never a fabricated TradingBox decision.
            failure = {'version': 'x.0.1', 'request_id': cycle, 'ts': now(), 'origin': 'intermediary',
                       'status': None, 'client_status': 502, 'error': type(error).__name__,
                       'duration_ms': round((time.monotonic() - started) * 1000, 3), 'body_base64': ''}
            try:
                self.server.record('response', failure)
            except OSError:
                pass
            self.send_error(502, 'Upstream exchange unavailable')
            return
        finally:
            if connection:
                connection.close()
        try:
            self.server.record('response', response_record)
        except OSError as error:
            print(f'Response archive failed for {cycle}: {type(error).__name__}', file=sys.stderr, flush=True)
        try:
            self.send_response_only(response.status, response.reason)
            excluded = connection_fields(response_headers) | {'content-length'}
            for key, value in response_headers:
                if key.lower() not in excluded:
                    self.send_header(key, value)
            if self.command == 'HEAD' or response.status == 304:
                length = response.getheader('Content-Length')
                if length is not None:
                    self.send_header('Content-Length', length)
            elif response.status != 204:
                self.send_header('Content-Length', str(len(response_body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(response_body)
        except (TimeoutError, OSError):
            self.server.record('delivery', {'request_id': cycle, 'ts': now(), 'error': 'Quantower connection closed before reply completed'})

    def local_reply(self, cycle, started, body):
        path = urlsplit(self.path).path
        status = 200
        reply = {'origin': 'x.0.1', 'forwarded_to_tradingbox': False}
        connection = None
        try:
            if self.command == 'GET' and path == '/api/hcamm/commands':
                reply.update(commands=[], verdicts=[])
            elif self.command == 'POST' and path == '/api/hcamm/events':
                if len(body) > 1024 * 1024:
                    status, reply['error'] = 413, 'Signal batch exceeds local receiver size limit'
                else:
                    # Fixed loopback endpoint: no TradingBox call is made in local mode.
                    connection = http.client.HTTPConnection('127.0.0.1', self.server.receiver_port, timeout=30)
                    connection.request('POST', '/capture/signals', body=body, headers={
                        'Authorization': 'Bearer ' + self.server.receiver_token, 'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    status = response.status
                    reply.update(json.loads(response.read()))
            else:
                status, reply['error'] = 404, 'No local receiver for this method/path; TradingBox forwarding is disabled'
        except (OSError, http.client.HTTPException, ValueError):
            status, reply['error'] = 503, 'Local signal receiver unavailable; no TradingBox forwarding'
        finally:
            if connection:
                connection.close()
        encoded = json.dumps(reply, separators=(',', ':')).encode()
        reason = http.client.responses.get(status, 'Local response')
        headers = [('Content-Type', 'application/json'), ('Content-Length', str(len(encoded)))]
        record = {'version': 'x.0.1', 'request_id': cycle, 'ts': now(), 'origin': 'x.0.1',
                  'method': self.command, 'path': self.path, 'status': status, 'reason': reason,
                  'headers': headers, 'duration_ms': round((time.monotonic() - started) * 1000, 3),
                  'body_bytes': len(encoded), 'body_base64': base64.b64encode(encoded).decode()}
        try:
            self.server.record('response', record)
        except OSError as error:
            print(f'Local response archive failed for {cycle}: {type(error).__name__}', file=sys.stderr, flush=True)
        self.send_response_only(status, reason)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header('Connection', 'close')
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except OSError:
            pass

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _handle
