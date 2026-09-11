"""Bounded opaque observation archive, independent of executable capture events."""

import base64
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .raw_log import RawLog

MAX_LOG_BODY = 65536


class LoggingStore:
    def __init__(self, directory, *, max_records=2000, max_bytes=8 * 1024 * 1024):
        if max_records < 1 or max_bytes < MAX_LOG_BODY:
            raise ValueError('Invalid logging retention limits')
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.max_records, self.max_bytes = max_records, max_bytes
        self.db = sqlite3.connect(Path(directory) / 'observations.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA wal_autocheckpoint=64')
        self.db.execute('PRAGMA journal_size_limit=1048576')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS observations (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, receipt_id TEXT UNIQUE,
                received_at TEXT, content_type TEXT, digest TEXT, body BLOB);
            CREATE TABLE IF NOT EXISTS logging_meta (id INTEGER PRIMARY KEY, evicted INTEGER);
            INSERT OR IGNORE INTO logging_meta VALUES(1,0);
        ''')
        if 'metadata' not in {r[1] for r in self.db.execute('PRAGMA table_info(observations)')}:
            self.db.execute("ALTER TABLE observations ADD COLUMN metadata TEXT DEFAULT '{}'")
            self.db.commit()

    def accept(self, body, content_type='application/octet-stream', *, metadata=None):
        if not isinstance(body, bytes) or len(body) > MAX_LOG_BODY:
            raise ValueError('Logging body exceeds 64 KiB')
        identity, now = str(uuid4()), datetime.now(UTC).isoformat()
        metadata = json.dumps(metadata or {})
        with self.lock, self.db:
            self.db.execute('INSERT INTO observations(receipt_id,received_at,content_type,digest,body,metadata) VALUES(?,?,?,?,?,?)',
                            (identity, now, content_type[:200], hashlib.sha256(body).hexdigest(), body, metadata))
            rows = self.db.execute('SELECT seq,length(body) AS size FROM observations ORDER BY seq DESC').fetchall()
            total, cutoff = 0, None
            for index, row in enumerate(rows):
                total += row['size']
                if index >= self.max_records or total > self.max_bytes:
                    cutoff = row['seq']
                    break
            if cutoff is not None:
                removed = self.db.execute('DELETE FROM observations WHERE seq<=?', (cutoff,)).rowcount
                self.db.execute('UPDATE logging_meta SET evicted=evicted+? WHERE id=1', (removed,))
        return {'receipt_id': identity, 'received_at': now, 'status': 'logged', 'durable': True,
                'forwarded': False, 'executed': False, 'retention': 'rolling'}

    def feed(self, before=0, limit=100):
        if type(before) is not int or before < 0 or not 1 <= limit <= 100:
            raise ValueError('Invalid logging cursor')
        with self.lock:
            rows = self.db.execute('SELECT * FROM observations WHERE (?=0 OR seq<?) ORDER BY seq DESC LIMIT ?',
                                   (before, before, limit)).fetchall()
            count, size = self.db.execute('SELECT count(*),coalesce(sum(length(body)),0) FROM observations').fetchone()
            evicted = self.db.execute('SELECT evicted FROM logging_meta WHERE id=1').fetchone()[0]
        records = []
        for row in rows:
            item = dict(row)
            item['metadata'] = json.loads(item['metadata'])
            raw = bytes(item.pop('body'))
            item.update(body_bytes=len(raw), data_base64=base64.b64encode(raw).decode())
            # Reuse the volatile monitor's redaction; originals are private archive bytes.
            preview = RawLog()
            preview.append('in', 'logging', raw.decode('utf-8', errors='replace'))
            view = preview.stream_snapshot()['events'][0]
            item.update(preview=view['raw'], preview_truncated=view['truncated'])
            try:
                value = json.loads(view['raw'])
                event = value.get('event', value) if isinstance(value, dict) else {}
                item['source'] = event.get('source') if isinstance(event, dict) else None
                item['kind'] = event.get('kind') or event.get('type') if isinstance(event, dict) else None
            except (ValueError, RecursionError):
                pass
            records.append(item)
        return {'records': records, 'next_before': rows[-1]['seq'] if rows else before,
                'count': count, 'body_bytes': size, 'evicted': evicted,
                'max_records': self.max_records, 'max_bytes': self.max_bytes}

    def close(self):
        with self.lock:
            self.db.close()
