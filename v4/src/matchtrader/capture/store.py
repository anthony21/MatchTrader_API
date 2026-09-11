"""Transactional deduplication plus a bounded, atomically replaced CSV view.

SQLite retains identity tombstones after the CSV rolls. A dispatch intent is
committed before any network write; a crash leaves it uncertain, never retryable.
"""

import csv
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Condition, Event, Lock, RLock, Thread
from uuid import uuid4

from .event import CaptureEvent
from .mapping import MappingLedger
from .meaning import meaning
from .raw_log import RawLog


def _clean_broker_time(value):
    """Blank/whitespace-only broker timestamps must never reach SQL: observe_destination's
    COALESCE relies on NULL, not '', to mean "no value seen yet", or a real timestamp already
    on record could be replaced by an empty string on a later, timestamp-less read-back."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _execution_quantity(volume):
    """Normalize a quantity used to key a closing execution. The broker may spell the same
    volume '0.5' on one read and '0.50' on the next; without normalizing, one close would be
    keyed twice and its volume double-counted into a false complete-closure claim."""
    try:
        return str(Decimal(str(volume)).normalize())
    except (ArithmeticError, TypeError, ValueError):
        return str(volume)


class CaptureStore:
    def __init__(self, directory: Path, limit=1000, broker="", *, background_exports=False):
        if not 1 <= limit <= 100000:
            raise ValueError("CSV limit must be between 1 and 100000")
        directory.mkdir(parents=True, exist_ok=True)
        self.csv_path = directory / "trades.csv"
        self.raw_log = RawLog()
        self.limit = limit
        self.lock = RLock()
        self.changed = Condition(self.lock)
        self.revision = 0
        self.closed = False
        self.db = sqlite3.connect(directory / "capture.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY, source_key TEXT UNIQUE, source TEXT,
                source_order_id TEXT, source_position_id TEXT DEFAULT '',
                destination TEXT DEFAULT '', broker_order_id TEXT DEFAULT '',
                broker_position_id TEXT DEFAULT '', state TEXT DEFAULT 'observed',
                updated_at TEXT, resolved_at TEXT, last_request TEXT DEFAULT '',
                lots TEXT DEFAULT '', symbol TEXT DEFAULT '', side TEXT DEFAULT '',
                order_type TEXT DEFAULT '', scope TEXT, last_event_at TEXT DEFAULT '',
                source_quantity TEXT DEFAULT '', source_state TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY, event_key TEXT UNIQUE, digest TEXT, trade_id TEXT,
                received_at TEXT, payload TEXT, decision TEXT DEFAULT 'captured', reason TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS attempts (
                trade_id TEXT, action_key TEXT, state TEXT, PRIMARY KEY(trade_id,action_key));
        """)
        try:
            self.mappings = MappingLedger(self.db, broker)
        except Exception:
            self.db.close()
            raise
        with self.db:
            self.db.execute("UPDATE trades SET state='uncertain' WHERE state='dispatching'")
            self.db.execute("UPDATE attempts SET state='uncertain' WHERE state='dispatching'")
        self.export_error = False
        self.export_lock = Lock()
        self.export_dirty = Event()
        self.export_stop = Event()
        self.export_worker = None
        if background_exports:
            self.export_worker = Thread(target=self._export_loop, name='capture-csv', daemon=True)
            self.export_worker.start()

    def record(self, event: CaptureEvent):
        raw = event.model_dump_json()
        digest = hashlib.sha256(raw.encode()).hexdigest()
        key = json.dumps([event.machine, event.event_id])
        scope = json.dumps(event.scope)
        now = datetime.now(UTC).isoformat()
        with self.lock, self.db:
            old = self.db.execute("SELECT * FROM events WHERE event_key=?", (key,)).fetchone()
            if old:
                if old["digest"] != digest and CaptureEvent.model_validate_json(old["payload"]) != event:
                    raise ValueError("Event ID reused with different data")
                return dict(old), True
            trade = None
            if event.order_id:
                source_key = json.dumps([*event.scope, event.order_id])
                trade = self.db.execute("SELECT * FROM trades WHERE source_key=?", (source_key,)).fetchone()
            elif event.position_id:
                matches = self.db.execute(
                    "SELECT t.* FROM trades t JOIN identity_links l ON l.trade_id=t.trade_id "
                    "WHERE l.side='source' AND l.kind='position' AND l.scope=? AND l.native_id=?",
                    (scope, event.position_id),
                ).fetchall()
                trade = matches[0] if len(matches) == 1 else None
            if not trade and event.order_id:
                identity = str(uuid4())
                self.db.execute(
                    "INSERT INTO trades(trade_id,source_key,source,source_order_id,updated_at,scope) "
                    "VALUES(?,?,?,?,?,?)",
                    (identity, source_key, event.source, event.order_id, now, scope),
                )
                trade = self.db.execute("SELECT * FROM trades WHERE trade_id=?", (identity,)).fetchone()
            identity = trade["trade_id"] if trade else None
            if identity:
                self.mappings.source_event(identity, event)
                self.db.execute(
                    "UPDATE trades SET updated_at=?,source_state=? WHERE trade_id=?",
                    (now, event.status or event.kind, identity),
                )
                if event.kind == "ACCEPTED" and event.action in {"CREATE", "EDIT"}:
                    self.db.execute("UPDATE trades SET source_quantity=? WHERE trade_id=?",
                                    (str(event.order_quantity or event.quantity), identity))
                if not trade["destination"]:
                    self.db.execute(
                        "UPDATE trades SET symbol=?,side=?,order_type=? WHERE trade_id=?",
                        (event.symbol, event.side, event.order_type, identity),
                    )
                    if (event.kind == "ORDER" and event.status in {"Cancelled", "Refused"}) or (
                        event.kind == "POSITION" and event.status == "Removed"
                    ):
                        self.db.execute(
                            "UPDATE trades SET state='resolved',resolved_at=? WHERE trade_id=?",
                            (now, identity),
                        )
                if event.kind == "FILL" and event.position_id:
                    positions = self.mappings.ids(identity, 'source', 'position')
                    self.db.execute(
                        "UPDATE trades SET source_position_id=? WHERE trade_id=?",
                        (positions[0] if len(positions) == 1 else '', identity),
                    )
                # Attribution may be learned from the create result after OrderAdded.
                if event.action == "CREATE" and event.source != "UNKNOWN":
                    self.db.execute(
                        "UPDATE trades SET source=? WHERE trade_id=? AND source='UNKNOWN'",
                        (event.source, identity),
                    )
            self.db.execute(
                "INSERT INTO events(event_key,digest,trade_id,received_at,payload) VALUES(?,?,?,?,?)",
                (key, digest, identity, now, raw),
            )
            row = dict(self.db.execute("SELECT * FROM events WHERE event_key=?", (key,)).fetchone())
        self.notify_stream()
        self.export()
        return row, False

    def trade(self, identity):
        with self.lock:
            row = self.db.execute("SELECT * FROM trades WHERE trade_id=?", (identity,)).fetchone()
            return dict(row) if row else None

    def update(self, identity, **values):
        allowed = {
            "destination",
            "broker_order_id",
            "broker_position_id",
            "state",
            "resolved_at",
            "last_request",
            "lots",
            "symbol",
            "side",
            "order_type",
            "last_event_at",
        }
        if not values or not set(values) <= allowed:
            raise ValueError("Invalid trade update")
        values["updated_at"] = datetime.now(UTC).isoformat()
        with self.lock, self.db:
            self.db.execute(
                "UPDATE trades SET " + ",".join(k + "=?" for k in values) + " WHERE trade_id=?",
                (*values.values(), identity),
            )
            trade = self.trade(identity)
            if trade and trade['destination']:
                scope = self.mappings.destination_scope(trade['destination'])
                for kind in ('order', 'position'):
                    self.mappings.link(identity, 'destination', scope, kind, trade['broker_' + kind + '_id'],
                                       'broker identity', values['updated_at'])
                if 'lots' in values:
                    self.mappings.quantities(identity, 'destination', scope, values['lots'], None, None,
                                             'lots', values['updated_at'])
        self.export()

    def claim(self, identity, action_key, *, event=None, destination="", request=None):
        with self.lock, self.db:
            trade = self.trade(identity)
            if not trade or trade["state"] in {"uncertain", "dispatching", "resolved"}:
                return False
            if action_key == "CREATE" and (trade["broker_order_id"] or trade["broker_position_id"]):
                return False
            try:
                self.db.execute("INSERT INTO attempts VALUES(?,?,'dispatching')", (identity, action_key))
            except sqlite3.IntegrityError:
                return False
            self.db.execute("UPDATE trades SET state='dispatching' WHERE trade_id=?", (identity,))
            if event is not None:
                self.db.execute("INSERT INTO action_history VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    identity, action_key, self.mappings.broker, destination, event.request_id, event.action,
                    json.dumps(request, default=str), 'dispatching', '', '', datetime.now(UTC).isoformat(),
                ))
        return True

    def finish(self, identity, action_key, state):
        with self.lock, self.db:
            self.db.execute(
                "UPDATE attempts SET state=? WHERE trade_id=? AND action_key=?", (state, identity, action_key)
            )
            trade = self.trade(identity)
            self.db.execute(
                "UPDATE action_history SET outcome=?,broker_order_id=?,broker_position_id=?,updated_at=? "
                "WHERE trade_id=? AND action_key=?", (state, trade['broker_order_id'], trade['broker_position_id'],
                                                     datetime.now(UTC).isoformat(), identity, action_key))

    def mapping_view(self, destination):
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM trades WHERE destination=? OR destination='' ORDER BY updated_at DESC LIMIT 200",
                (destination,),
            ).fetchall()
            return [self.mappings.snapshot(dict(row)) for row in rows]

    def observe_positions(self, identity, destination, positions):
        with self.lock, self.db:
            scope = self.mappings.destination_scope(destination)
            now = datetime.now(UTC).isoformat()
            for position in positions:
                self.mappings.link(identity, 'destination', scope, 'position', position.id,
                                   'broker order/position relationship', now)
                self.mappings.position('destination', scope, position.id, position.volume, now)
                self.mappings.observe_destination(
                    identity, scope, position.id, 'open_positions', execution_key=position.id,
                    order_id=getattr(position, 'orderId', None), symbol=position.symbol, side=position.side,
                    volume=position.volume, open_price=position.openPrice,
                    open_time=_clean_broker_time(position.openTime),
                    open_time_millis=position.openTimeMillis, close_time=None, close_reason=None, at=now,
                )

    def observe_closed(self, identity, destination, trades):
        with self.lock, self.db:
            scope = self.mappings.destination_scope(destination)
            now = datetime.now(UTC).isoformat()
            for closed in trades:
                # order_id here is closingOrderID, not the opening orderId observe_positions above
                # stores under the same column; the two readers give the column different meanings.
                # execution_key discriminates each closing execution against the same position so
                # multiple partial closes are retained and their volumes can be summed. Both broker
                # execution IDs are optional, so the last resort composes the close time and volume:
                # the position id alone would collapse every partial close onto one row.
                stamp = getattr(closed, 'time', '') or ''
                execution_key = (getattr(closed, 'uid', None) or getattr(closed, 'closingOrderID', None)
                                 or f'{closed.id}@{stamp}:{_execution_quantity(closed.volume)}')
                self.mappings.observe_destination(
                    identity, scope, closed.id, 'closed_positions', execution_key=execution_key,
                    order_id=getattr(closed, 'closingOrderID', None), symbol=closed.symbol, side=closed.side,
                    volume=closed.volume, open_price=getattr(closed, 'openPrice', None),
                    open_time=_clean_broker_time(getattr(closed, 'openTime', None)), open_time_millis=None,
                    close_time=getattr(closed, 'time', None),
                    close_reason=getattr(closed, 'closeReason', None), at=now,
                )

    def decision(self, seq, status, reason):
        with self.lock, self.db:
            self.db.execute("UPDATE events SET decision=?,reason=? WHERE seq=?", (status, reason, seq))
        self.notify_stream()
        self.export()

    def notify_stream(self):
        with self.changed:
            self.revision += 1
            self.changed.notify_all()

    def stream_snapshot(self, after=-1, timeout=10):
        """Wait for committed changes; coalesce slow readers into a bounded snapshot."""
        with self.changed:
            self.changed.wait_for(lambda: self.closed or self.revision != after, timeout)
            if self.closed:
                return None
            if self.revision == after:
                return {"revision": after}  # Heartbeat; no database read while idle.
            return {"revision": self.revision, "events": self.feed()}

    def feed(self):
        with self.lock:
            rows = self.db.execute(
                "SELECT e.*,t.source AS origin_source FROM events e LEFT JOIN trades t ON e.trade_id=t.trade_id "
                "ORDER BY e.seq DESC LIMIT 200"
            ).fetchall()
            events = [
                {
                    "id": "native:" + str(r["seq"]),
                    **json.loads(r["payload"]),
                    "trade_id": r["trade_id"],
                    "received_at": r["received_at"],
                    "decision": r["decision"],
                    "reason": r["reason"],
                }
                for r in rows
            ]
            for event, row in zip(events, rows, strict=True):
                event['meaning'] = meaning(event, row['origin_source'])
            return events

    def export(self):
        if self.export_worker:
            self.export_dirty.set()
        else:
            self._export_now()

    def _export_loop(self):
        while True:
            self.export_dirty.wait()
            self.export_dirty.clear()
            self._export_now()
            if self.export_stop.is_set():
                break

    def _export_now(self):
        # Snapshot under the journal lock; filesystem work never holds that lock.
        with self.export_lock:
            with self.lock:
                cursor = self.db.execute("SELECT * FROM trades ORDER BY updated_at DESC LIMIT ?", (self.limit,))
                fields = [d[0] for d in cursor.description]
                rows = [dict(row) for row in cursor]
            try:
                target = self.csv_path.with_suffix(".tmp")
                with target.open("w", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    for row in rows:
                        writer.writerow({
                            k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                            for k, v in row.items()
                        })
                target.replace(self.csv_path)
                self.export_error = False
            except OSError:
                self.export_error = True

    def close(self):
        self.raw_log.close()
        if self.export_worker:
            self.export_stop.set()
            self.export_dirty.set()
            self.export_worker.join()
        with self.changed:
            self.closed = True
            self.changed.notify_all()
            self.db.close()
