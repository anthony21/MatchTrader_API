"""Explicitly armed TradingBox signal forwarding; no retries or historical replay."""

import hmac
import http.client
import json
import os
import tempfile
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import unquote, urlsplit
from uuid import uuid4

HOP = {'host', 'content-length', 'connection', 'keep-alive', 'proxy-authenticate',
       'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'}
MAX_RESPONSE = 1024 * 1024
MAX_REQUEST = 1024 * 1024
METHODS = {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'}


def validate_target(target):
    parsed = urlsplit(target)
    decoded = unquote(parsed.path)
    if (not target.startswith('/api/hcamm/') or parsed.scheme or parsed.netloc
            or parsed.fragment or any(ord(c) < 33 or ord(c) > 126 for c in target)
            or not decoded.startswith('/api/hcamm/') or '\\' in decoded
            or any(part in {'.', '..'} for part in decoded.split('/'))):
        raise ValueError('Expected an origin-form /api/hcamm/ request target')
    return target



def end_to_end(headers):
    excluded = set(HOP)
    for name, value in headers:
        if name.lower() == 'connection':
            excluded.update(part.strip().lower() for part in value.split(','))
    return [(name, value) for name, value in headers if name.lower() not in excluded]


def validate_url(value):
    url = urlsplit(value)
    if (url.scheme != 'https' or url.hostname not in {'tradingbox.pro', 'tradingbox.org'}
            or url.username or url.password or url.port not in {None, 443}
            or url.query or url.fragment or url.path != '/api/hcamm/events'):
        raise ValueError('Use https://tradingbox.pro/api/hcamm/events or https://tradingbox.org/api/hcamm/events')
    return value


def send_once(url, headers, body, *, method='POST'):
    """Raw HTTP body/status/end-to-end headers, without redirects or decompression."""
    parsed = urlsplit(url)
    connection = http.client.HTTPSConnection(parsed.hostname, timeout=15)
    try:
        target = parsed.path + ('?' + parsed.query if parsed.query else '')
        connection.putrequest(method, target, skip_accept_encoding=True)
        for name, value in end_to_end(headers):
            if name.lower() != 'expect':
                connection.putheader(name, value)
        connection.putheader('Content-Length', str(len(body)))
        connection.endheaders(body)
        response = connection.getresponse()
        payload = response.read(MAX_RESPONSE + 1)
        if len(payload) > MAX_RESPONSE:
            raise OSError('Upstream response exceeds diagnostic transport limit')
        response_headers = end_to_end(response.getheaders())
        if method == 'HEAD' or response.status == 304:
            response_headers += [(k, v) for k, v in response.getheaders() if k.lower() == 'content-length']
        return response.status, response.reason, response_headers, payload
    finally:
        connection.close()


class TradingBoxForwarder:
    def __init__(self, path, store, raw_log, *, api_key='', auth_header='X-HCAMM-Key', send=send_once):
        if auth_header.lower() not in {'x-hcamm-key', 'x-api-key', 'authorization'}:
            raise ValueError('Unsupported TradingBox authentication header')
        if any(ord(c) < 32 or ord(c) > 126 for c in api_key):
            raise ValueError('TradingBox key must be a single-line ASCII header value')
        self.path, self.store, self.raw_log = Path(path), store, raw_log
        self.api_key, self.auth_header, self.send = api_key, auth_header, send
        self.lock = Lock()
        self.url = ''
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding='utf-8'))['url']
            self.url = validate_url(saved) if saved else ''
        self.enabled = self.live = False
        self.generation = 0
        self.in_flight = self.sent = self.failed = self.previewed = 0
        self.last_result = None

    def status(self):
        with self.lock:
            return {'url': self.url, 'enabled': self.enabled, 'live': self.live, 'generation': self.generation,
                    'auth_header': self.auth_header, 'key_configured': bool(self.api_key),
                    'in_flight': self.in_flight, 'sent': self.sent, 'failed': self.failed,
                    'previewed': self.previewed, 'last_result': self.last_result,
                    'endpoint': '/api/hcamm/events'}

    def configure(self, value):
        if not isinstance(value, dict) or set(value) != {'url', 'enabled', 'live'}:
            raise ValueError('Provide URL, forwarding and live flags')
        if type(value['enabled']) is not bool or type(value['live']) is not bool:
            raise ValueError('Forwarding flags must be booleans')
        url = validate_url(value['url']) if value['url'] else ''
        if value['enabled'] and not url:
            raise ValueError('Configure the TradingBox URL first')
        if value['live'] and (not value['enabled'] or not self.api_key):
            raise ValueError('Live requires forwarding enabled and TB_FORWARD_API_KEY configured')
        with self.lock:
            if url != self.url:
                if self.enabled or self.in_flight:
                    raise ValueError('Turn forwarding off and wait for active requests before changing the URL')
                self.path.parent.mkdir(parents=True, exist_ok=True)
                descriptor, name = tempfile.mkstemp(dir=self.path.parent, suffix='.tmp')
                try:
                    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                        json.dump({'url': url}, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(name, self.path)
                finally:
                    Path(name).unlink(missing_ok=True)
            self.url, self.enabled, self.live = url, value['enabled'], value['live']
            self.generation += 1
        return self.status()

    def authorized(self, headers):
        values = [v for k, v in headers if k.lower() == self.auth_header.lower()]
        return bool(self.api_key) and len(values) == 1 and hmac.compare_digest(values[0].encode(), self.api_key.encode())

    def ticket(self):
        with self.lock:
            return self.generation, self.enabled, self.live

    def _record(self, direction, body, content_type, cycle, **metadata):
        result = self.store.accept(body[:65536], content_type, metadata={
            'transport': 'tradingbox', 'direction': direction, 'cycle_id': cycle,
            'body_bytes_original': len(body), 'body_truncated': len(body) > 65536, **metadata})
        self.raw_log.append(direction, 'tradingbox',
                            f'Cycle {cycle}\n' + body.decode('utf-8', errors='replace'), self.api_key)
        return result

    def receive(self, headers, body, ticket, *, method='POST', target='/api/hcamm/events'):
        validate_target(target)
        if method not in METHODS or len(body) > MAX_REQUEST:
            raise ValueError('Unsupported method or request size')
        # Never expose authentication that may appear in query parameters.
        request_meta = {'method': method, 'path': urlsplit(target).path,
                        'has_query': '?' in target}
        cycle = str(uuid4())
        content_type = next((v for k, v in headers if k.lower() == 'content-type'), 'application/octet-stream')
        # A failed request-log commit aborts before any outbound request.
        receipt = self._record('in', body, content_type, cycle, **request_meta)
        with self.lock:
            active = ticket == (self.generation, True, True) and self.enabled and self.live
            if active:
                self.in_flight += 1
                url = 'https://' + urlsplit(self.url).netloc + target
            else:
                self.previewed += 1
        if not active:
            result = {**receipt, 'status': 'logged_only', 'cycle_id': cycle,
                      'forwarded': False, 'executed': False, 'reason': 'Forwarding off, preview mode or controls changed'}
            self.raw_log.append('out', 'tradingbox', result)
            return 202, 'Accepted', [('Content-Type', 'application/json')], json.dumps(result).encode()
        started = monotonic()
        try:
            status, reason, response_headers, payload = self.send(url, headers, body, method=method)
            outcome = {'cycle_id': cycle, 'upstream_status': status, 'origin': 'tradingbox',
                       'duration_ms': round((monotonic() - started) * 1000, 3), **request_meta}
            with self.lock:
                self.sent += 1
                self.last_result = outcome
            try:
                content_type = next((v for k, v in response_headers if k.lower() == 'content-type'), 'application/octet-stream')
                self._record('out', payload, content_type, cycle, **{k: v for k, v in outcome.items() if k != 'cycle_id'})
            except Exception:
                # Upstream may already have acted. Preserve its reply; never retry.
                with self.lock:
                    self.last_result = {**outcome, 'response_log_failed': True}
            return status, reason, response_headers, payload
        except Exception:
            outcome = {'cycle_id': cycle, 'origin': 'intermediary', 'status': 'uncertain',
                       'error': 'TradingBox delivery outcome unknown; do not automatically retry', **request_meta}
            with self.lock:
                self.failed += 1
                self.last_result = outcome
            payload = json.dumps(outcome).encode()
            try:
                self._record('out', payload, 'application/json', cycle, status='uncertain')
            except Exception:
                pass
            return 502, 'Bad Gateway', [('Content-Type', 'application/json')], payload
        finally:
            with self.lock:
                self.in_flight -= 1

    def close(self):
        with self.lock:
            self.enabled = self.live = False
            self.generation += 1
