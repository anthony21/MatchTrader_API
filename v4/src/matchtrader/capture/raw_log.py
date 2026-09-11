"""Bounded, volatile application-message diagnostics; never a trading journal."""

import json
import re
from collections import deque
from datetime import UTC, datetime
from threading import Condition


class RawLog:
    def __init__(self, max_entries=500, max_bytes=2 * 1024 * 1024):
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.entries = deque()
        self.bytes = 0
        self.revision = 0
        self.evicted = 0
        self.closed = False
        self.changed = Condition()

    def append(self, direction, transport, raw, secret=''):
        if isinstance(raw, bytes):
            text = f'[Binary message: {len(raw)} bytes; content omitted]'
        else:
            text = raw if isinstance(raw, str) else json.dumps(raw)
            if secret:
                text = text.replace(secret, '[redacted]')
            # Includes malformed JSON: never display authentication values.
            text = re.sub(r'(?i)("(?:password|token|authorization|api_key|apiKey|aiKey|x-hcamm-key|cookie|secret)"\s*:\s*")[^"]*', r'\1[redacted]', text)
            text = re.sub(r'(?i)Bearer\s+[^\s"\\]+', 'Bearer [redacted]', text)
        truncated = len(text.encode()) > 32768
        text = text.encode()[:32768].decode('utf-8', errors='ignore')
        with self.changed:
            self.revision += 1
            row = {'id': self.revision, 'received_at': datetime.now(UTC).isoformat(),
                   'direction': direction, 'transport': transport, 'raw': text, 'truncated': truncated}
            size = len(json.dumps(row).encode())
            self.entries.append((row, size))
            self.bytes += size
            while len(self.entries) > self.max_entries or self.bytes > self.max_bytes:
                self.bytes -= self.entries.popleft()[1]
                self.evicted += 1
            self.changed.notify_all()

    def stream_snapshot(self, after=-1, timeout=10):
        with self.changed:
            self.changed.wait_for(lambda: self.closed or self.revision != after, timeout)
            if self.closed:
                return None
            result = {'revision': self.revision}
            if self.revision != after:
                result.update(events=[row for row, _ in reversed(self.entries)], bytes=self.bytes,
                              max_bytes=self.max_bytes, max_entries=self.max_entries, evicted=self.evicted)
            return result

    def close(self):
        with self.changed:
            self.closed = True
            self.changed.notify_all()
