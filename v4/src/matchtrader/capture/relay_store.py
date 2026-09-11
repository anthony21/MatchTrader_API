"""Durable opaque relay-log archive. This store never dispatches trades."""

import base64
import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import UUID

CHUNK_BYTES = 8192


class RelayLogStore:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.db = sqlite3.connect(directory / 'relay.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS chunks (
                seq INTEGER PRIMARY KEY, stream_id TEXT, machine TEXT, filename TEXT,
                offset INTEGER, digest TEXT, payload BLOB, received_at TEXT,
                UNIQUE(stream_id, offset));
            CREATE TABLE IF NOT EXISTS streams (
                stream_id TEXT PRIMARY KEY, machine TEXT, filename TEXT, next_offset INTEGER);
        ''')

    def accept(self, message):
        if not isinstance(message, dict) or set(message) != {
                'version', 'stream_id', 'machine', 'filename', 'offset', 'sha256', 'data_base64'}:
            raise ValueError('Invalid relay envelope')
        if message['version'] != '1.0.0':
            raise ValueError('Unsupported relay envelope version')
        stream = message['stream_id']
        if not isinstance(stream, str):
            raise ValueError('Invalid stream identity')
        UUID(stream)
        machine, filename = message['machine'], message['filename']
        if not isinstance(machine, str) or not 1 <= len(machine) <= 100:
            raise ValueError('Invalid machine')
        if (not isinstance(filename, str) or not 1 <= len(filename) <= 240
                or '/' in filename or '\\' in filename or not filename.endswith(('.log', '.jsonl'))):
            raise ValueError('Invalid filename')
        offset = message['offset']
        if type(offset) is not int or not 0 <= offset <= 2**63 - CHUNK_BYTES:
            raise ValueError('Invalid offset')
        try:
            payload = base64.b64decode(message['data_base64'], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid log bytes') from exc
        digest = hashlib.sha256(payload).hexdigest()
        if not 1 <= len(payload) <= CHUNK_BYTES or message['sha256'] != digest:
            raise ValueError('Invalid log checksum or size')
        with self.lock, self.db:
            existing = self.db.execute('SELECT * FROM chunks WHERE stream_id=? AND offset=?', (stream, offset)).fetchone()
            if existing:
                if (existing['machine'], existing['filename'], existing['digest'], bytes(existing['payload'])) != (machine, filename, digest, payload):
                    raise ValueError('Relay identity conflict')
            else:
                previous = self.db.execute('SELECT * FROM streams WHERE stream_id=?', (stream,)).fetchone()
                if previous and (previous['machine'], previous['filename']) != (machine, filename):
                    raise ValueError('Relay stream identity conflict')
                if offset != (previous['next_offset'] if previous else 0):
                    raise ValueError('Relay log gap')
                self.db.execute('INSERT INTO chunks(stream_id,machine,filename,offset,digest,payload,received_at) VALUES(?,?,?,?,?,?,?)',
                                (stream, machine, filename, offset, digest, payload, datetime.now(UTC).isoformat()))
                self.db.execute('INSERT INTO streams VALUES(?,?,?,?) ON CONFLICT(stream_id) DO UPDATE SET next_offset=excluded.next_offset',
                                (stream, machine, filename, offset + len(payload)))
        return {'version': '1.0.0', 'stream_id': stream, 'offset': offset, 'next_offset': offset + len(payload),
                'sha256': digest, 'durable': True, 'duplicate': existing is not None}

    def feed(self, after=0, limit=100):
        if type(after) is not int or after < 0 or not 1 <= limit <= 100:
            raise ValueError('Invalid relay page')
        with self.lock:
            rows = self.db.execute('SELECT * FROM chunks WHERE seq>? ORDER BY seq LIMIT ?', (after, limit)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['data_base64'] = base64.b64encode(item.pop('payload')).decode('ascii')
            result.append(item)
        return {'records': result, 'next_after': result[-1]['seq'] if result else after}

    def status(self):
        with self.lock:
            row = self.db.execute('SELECT count(*),coalesce(sum(length(payload)),0),max(received_at) FROM chunks').fetchone()
            streams = self.db.execute('SELECT count(*) FROM streams').fetchone()[0]
        return {'chunks': row[0], 'bytes': row[1], 'last_received_at': row[2], 'streams': streams, 'durable': True}

    def close(self):
        with self.lock:
            self.db.close()
