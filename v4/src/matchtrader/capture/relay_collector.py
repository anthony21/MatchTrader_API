"""Mirror every byte of relay .log/.jsonl files, checkpointing only durable ACKs."""

import argparse
import base64
import hashlib
import json
import platform
import sqlite3
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values

from .lifecycle import stopping
from .relay_store import CHUNK_BYTES


class RelayCollector:
    def __init__(self, logs, state, endpoint, token, *, deliver=None):
        self.logs = Path(logs).resolve()
        if not self.logs.is_dir():
            raise ValueError('Relay log directory does not exist')
        uri = urlsplit(endpoint)
        if (uri.scheme != 'http' or uri.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or uri.path != '/relay/logs' or uri.query or uri.fragment or uri.username or uri.password):
            raise ValueError('Use the local /relay/logs endpoint')
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError('Configure the private local bridge token')
        self.endpoint, self.token = endpoint, token
        self.deliver = deliver or self._post
        self.machine = platform.node()
        state = Path(state)
        state.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(state)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, stream TEXT, identity TEXT, offset INTEGER, prefix BLOB)')
        self.db.execute('CREATE TABLE IF NOT EXISTS pending(path TEXT PRIMARY KEY, message TEXT)')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _post(self, message):
        request = urllib.request.Request(self.endpoint, json.dumps(message).encode(),
                                         {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        with self.opener.open(request, timeout=10) as response:
            if response.status != 202:
                raise OSError('Receiver did not accept log chunk')
            return json.loads(response.read(16385))

    def poll(self):
        delivered = 0
        for pending in self.db.execute('SELECT * FROM pending ORDER BY path').fetchall():
            self._deliver_pending(pending['path'], json.loads(pending['message']))
            delivered += 1
        for path in sorted(self.logs.iterdir()):
            if not path.is_file() or path.is_symlink() or path.suffix not in {'.log', '.jsonl'}:
                continue
            with path.open('rb') as source:
                stat = path.stat()
                identity = f'{stat.st_dev}:{stat.st_ino}'
                previous = self.db.execute('SELECT * FROM files WHERE path=?', (path.name,)).fetchone()
                prefix = source.read(len(previous['prefix']) if previous else 32)
                reset = previous is None or previous['identity'] != identity or stat.st_size < previous['offset'] or prefix != bytes(previous['prefix'])
                if reset:
                    if previous and stat.st_size < previous['offset']:
                        print('Log file was truncated; recording a new stream:', path.name, flush=True)
                    stream, offset = str(uuid4()), 0
                    with self.db:
                        self.db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)', (path.name, stream, identity, offset, prefix))
                else:
                    stream, offset = previous['stream'], previous['offset']
                source.seek(offset)
                payload = source.read(CHUNK_BYTES)
            if not payload:
                continue
            # Prefer line boundaries, but retain even oversized/non-JSON lines byte-for-byte.
            newline = payload.rfind(b'\n')
            if newline >= 0:
                payload = payload[:newline + 1]
            digest = hashlib.sha256(payload).hexdigest()
            message = {'version': '1.0.0', 'stream_id': stream, 'machine': self.machine,
                       'filename': path.name, 'offset': offset, 'sha256': digest,
                       'data_base64': base64.b64encode(payload).decode('ascii')}
            with self.db:
                self.db.execute('INSERT INTO pending VALUES(?,?)', (path.name, json.dumps(message)))
                if not prefix and offset == 0:
                    self.db.execute('UPDATE files SET prefix=? WHERE path=?', (payload[:32], path.name))
            self._deliver_pending(path.name, message)
            delivered += 1
        return delivered

    def _deliver_pending(self, filename, message):
        payload = base64.b64decode(message['data_base64'])
        ack = self.deliver(message)
        if (not isinstance(ack, dict) or ack.get('durable') is not True
                or any(ack.get(k) != message[k] for k in ('version', 'stream_id', 'offset', 'sha256'))
                or ack.get('next_offset') != message['offset'] + len(payload)):
            raise ValueError('Invalid durable relay acknowledgement; checkpoint retained')
        with self.db:
            self.db.execute('UPDATE files SET offset=? WHERE path=? AND stream=?',
                            (message['offset'] + len(payload), filename, message['stream_id']))
            self.db.execute('DELETE FROM pending WHERE path=?', (filename,))

    def close(self):
        self.db.close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--logs', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--env', type=Path, default=Path('.env'))
    parser.add_argument('--endpoint', default='http://127.0.0.1:8765/relay/logs')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--stop-file', type=Path, help='Local launcher shutdown signal')
    args = parser.parse_args(argv)
    token = dotenv_values(args.env).get('AQF_BRIDGE_TOKEN') or ''
    collector = RelayCollector(args.logs, args.state, args.endpoint, token)
    failures = 0
    print('Relay collector ready; replaying existing logs and following new bytes.', flush=True)
    try:
        while not stopping(args.stop_file):
            try:
                count = collector.poll()
                failures = 0
                if count:
                    print(f'Durably delivered {count} log chunks.', flush=True)
                if args.once:
                    if not count:
                        break
                    continue
                if not count:
                    time.sleep(0.25)
            except (OSError, ValueError) as exc:
                if args.once:
                    raise
                failures = min(failures + 1, 6)
                print(f'Log delivery unavailable ({type(exc).__name__}); original files/checkpoints retained.', flush=True)
                time.sleep(min(5, 0.25 * 2**failures))
    except KeyboardInterrupt:
        pass
    finally:
        collector.close()


if __name__ == '__main__':
    main()
