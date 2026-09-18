"""Transactional deduplication plus a bounded, atomically replaced CSV view.

SQLite retains identity tombstones after the CSV rolls. A dispatch intent is
committed before any network write; a crash leaves it uncertain, never retryable.
"""

import csv
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .event import CaptureEvent


class CaptureStore:
    def __init__(self, directory: Path, limit=1000):
        if not 1 <= limit <= 100000:
            raise ValueError("CSV limit must be between 1 and 100000")
        directory.mkdir(parents=True, exist_ok=True)
        self.csv_path = directory / "trades.csv"
        self.limit = limit
        self.lock = RLock()
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
        with self.db:
            self.db.execute("UPDATE trades SET state='uncertain' WHERE state='dispatching'")
            self.db.execute("UPDATE attempts SET state='uncertain' WHERE state='dispatching'")
        self.export_error = False

    def record(self, event: CaptureEvent):
        raw = event.model_dump_json()
        digest = hashlib.sha256(raw.encode()).hexdigest()
        key = json.dumps([event.machine, event.event_id])
        scope = json.dumps(event.scope)
        now = datetime.now(UTC).isoformat()
        with self.lock, self.db:
            old = self.db.execute("SELECT * FROM events WHERE event_key=?", (key,)).fetchone()
            if old:
                if old["digest"] != digest:
                    raise ValueError("Event ID reused with different data")
                return dict(old), True
            trade = None
            if event.order_id:
                source_key = json.dumps([*event.scope, event.order_id])
                trade = self.db.execute("SELECT * FROM trades WHERE source_key=?", (source_key,)).fetchone()
            elif event.position_id:
                matches = self.db.execute(
                    "SELECT * FROM trades WHERE scope=? AND source_position_id=?",
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
                self.db.execute(
                    "UPDATE trades SET updated_at=?,source_quantity=?,source_state=? WHERE trade_id=?",
                    (now, str(event.quantity), event.status or event.kind, identity),
                )
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
                    self.db.execute(
                        "UPDATE trades SET source_position_id=? WHERE trade_id=?",
                        (event.position_id, identity),
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
        self.export()

    def claim(self, identity, action_key):
        with self.lock, self.db:
            trade = self.trade(identity)
            if not trade or trade["state"] in {"uncertain", "dispatching", "resolved"}:
                return False
            if action_key == "CREATE" and trade["broker_order_id"]:
                return False
            try:
                self.db.execute("INSERT INTO attempts VALUES(?,?,'dispatching')", (identity, action_key))
            except sqlite3.IntegrityError:
                return False
            self.db.execute("UPDATE trades SET state='dispatching' WHERE trade_id=?", (identity,))
        return True

    def finish(self, identity, action_key, state):
        with self.lock, self.db:
            self.db.execute(
                "UPDATE attempts SET state=? WHERE trade_id=? AND action_key=?", (state, identity, action_key)
            )

    def decision(self, seq, status, reason):
        with self.lock, self.db:
            self.db.execute("UPDATE events SET decision=?,reason=? WHERE seq=?", (status, reason, seq))
        self.export()

    def feed(self):
        with self.lock:
            rows = self.db.execute("SELECT * FROM events ORDER BY seq DESC LIMIT 200").fetchall()
            return [
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

    def export(self):
        with self.lock:
            try:
                rows = self.db.execute("SELECT * FROM trades ORDER BY updated_at DESC LIMIT ?", (self.limit,))
                fields = [d[0] for d in rows.description]
                target = self.csv_path.with_suffix(".tmp")
                with target.open("w", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    for row in rows:
                        # Spreadsheet formula injection protection for source-supplied text.
                        writer.writerow(
                            {
                                k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                                for k, v in dict(row).items()
                            }
                        )
                target.replace(self.csv_path)
                self.export_error = False
            except OSError:
                self.export_error = True  # Excel may hold the CSV; SQLite remains authoritative.

    def close(self):
        with self.lock:
            self.db.close()
