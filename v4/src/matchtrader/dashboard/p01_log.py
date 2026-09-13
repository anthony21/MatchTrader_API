"""Observe P01 diagnostic lines; never route these records to a broker."""

import hashlib
import json
import os
import platform
import re
from collections import OrderedDict, deque
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock
from uuid import uuid4


class P01Log:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = RLock()
        self.events = deque(maxlen=200)
        self.labels = OrderedDict()
        self.offset = 0
        self.identity = None
        self.pending = b''
        self.error = ''
        self.intents = deque(maxlen=200)
        # Lifecycle ends the tool reports: a per-label release ("level available again") and the
        # Close/Cancel All card. Each is turned into a cancel for the copy it ended, if one was sent.
        self.releases = deque(maxlen=200)

    def start(self):
        """Start at EOF: never replay historical intents after Start capture."""
        with self.lock:
            try:
                stat = self.path.stat()
                self.offset, self.identity = stat.st_size, (stat.st_dev, stat.st_ino)
            except OSError:
                self.offset, self.identity = 0, None
            self.pending = b''
            self.labels.clear()
            self.intents.clear()
            self.releases.clear()

    def poll(self):
        with self.lock:
            try:
                with self.path.open('rb') as source:
                    stat = os.fstat(source.fileno())
                    identity = (stat.st_dev, stat.st_ino)
                    if identity != self.identity or stat.st_size < self.offset:
                        self.offset, self.pending = 0, b''
                        self.labels.clear()
                    self.identity = identity
                    source.seek(self.offset)
                    block = source.read(65536)
                    self.offset = source.tell()
                self.error = ''
            except OSError:
                self.error = 'P01 log unavailable'
                return False
            lines = (self.pending + block).split(b'\n')
            self.pending = lines.pop()[-16384:]
            for line in lines:
                self.record(line[-16384:].decode('utf-8', errors='replace').strip())
            return bool(lines)

    def record(self, raw):
        stamp, _, text = raw.partition(' ')
        try:
            emitted = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if emitted.tzinfo is None:
                return
        except ValueError:
            return
        # Chart-origin boxes are labelled P01RR_HHmmss_n; level-origin boxes on charts with a
        # mint file are labelled L:<edge>@<wall>@<bar> (or M: for mirrored levels). Both are
        # the tool's own lifecycle ids and both are joined to P01_STATE.json by exact equality.
        match = re.search(r"id='([^']+)'", text) or re.search(r'P01RR_\d+_\d+|\b[LM]:(?:low|high|beyond)@\S+', text)
        label = match.group(1) if match and match.lastindex else (match.group() if match else '')
        values = dict(re.findall(r'\b(side|entry|sl|tp|type)=([^\s]+)', text))
        if label:
            previous = self.labels.get(label, {})
            values = {**previous, **values}
            self.labels[label] = values
            self.labels.move_to_end(label)
            while len(self.labels) > 200:
                self.labels.popitem(last=False)
        action, title = 'OBSERVE', 'P01 diagnostic'
        if 'box OPEN clicked' in text:
            action, title = 'INTENT', 'Open intent'
        elif text.startswith('FIRE '):
            action, title = 'SIGNAL', 'Signal fired'
        elif text.startswith('signal band x '):
            action, title = 'REMOVE', 'Signal band removed'
        elif 'level available again:' in text:
            action, title = 'RELEASE', 'Level released'
        elif text == 'card: Close/Cancel All':
            action, title = 'CLOSE_CANCEL_INTENT', 'Close / cancel all intent'
        elif text.startswith('card Close/Cancel All ->'):
            action, title = 'TOOL_RESULT', 'Close / cancel tool result'
        row_id = 'p01-' + uuid4().hex
        row = {
            'id': row_id, 'event_id': row_id, 'trade_id': label, 'source_label': label,
            'kind': 'P01_LOG', 'action': action, 'source': 'P01', 'account_id': '',
            'symbol': '', 'connection_id': '', 'machine': '', 'quantity': None,
            'side': {'0': 'BUY', '1': 'SELL'}.get(values.get('side'), ''),
            'price': values.get('entry'), 'sl': values.get('sl'), 'tp': values.get('tp'),
            'order_type': values.get('type'), 'emitted_at': emitted.isoformat(),
            'received_at': datetime.now(UTC).isoformat(), 'decision': 'observed',
            'reason': text, 'log_path': str(self.path),
            'meaning': {'source': {'code': 'P01', 'label': 'P01', 'basis': 'Local P01 diagnostic log'},
                        'event': {'label': 'P01 intent / log', 'description': 'Tool activity; not broker acknowledgement.'},
                        'action': {'label': title}, 'opened': {'state': 'unconfirmed', 'label': 'Not confirmed'},
                        'result': 'Logged only'},
        }
        self.events.append(row)
        if action == 'INTENT':
            self.intents.append(row)
        elif action in {'RELEASE', 'CLOSE_CANCEL_INTENT'}:
            self.releases.append(row)

    def drain_intents(self):
        with self.lock:
            rows = list(self.intents)
            self.intents.clear()
            return rows

    def drain_releases(self):
        with self.lock:
            rows = list(self.releases)
            self.releases.clear()
            return rows

    def signal(self, row):
        """Join only exact labeled state; a shared latest-state file can miss fast clicks."""
        with self.path.with_name('P01_STATE.json').open(encoding='utf-8-sig') as f:
            state = json.load(f, parse_float=Decimal)
        stamp = datetime.fromisoformat(state['utc'].replace('Z', '+00:00'))
        emitted = datetime.fromisoformat(row['emitted_at'])
        if (state.get('label') != row['trade_id'] or state.get('action') != 'open'
                or stamp.tzinfo is None or abs((stamp - emitted).total_seconds()) > 2
                or state.get('side') != {'BUY': 0, 'SELL': 1}.get(row['side'])
                or not isinstance(state.get('symbol'), str) or not state['symbol'].strip()
                or any(Decimal(str(state[k])) != Decimal(str(row[v]))
                       for k, v in [('entry', 'price'), ('sl', 'sl'), ('tp', 'tp')])):
            raise ValueError('P01 state does not match this labeled intent; no copy')
        if row.get('order_type') not in {'Limit', 'Stop'}:
            raise ValueError('P01 intent has no supported pending order type')
        identity = hashlib.sha256(json.dumps([str(self.path.resolve()), row['trade_id'], row['emitted_at']]).encode()).hexdigest()
        return {'clientEventId': 'p01-' + identity, 'machineId': platform.node(), 'source': 'P01_LOG',
                'kind': 'intent', 'timestampUtc': row['emitted_at'], 'label': row['trade_id'],
                'symbol': state['symbol'], 'side': row['side'], 'entry': row['price'],
                'stopLoss': row['sl'], 'takeProfit': row['tp'], 'copyOrderType': row['order_type'].upper()}

    def feed(self):
        with self.lock:
            return list(reversed(self.events))
