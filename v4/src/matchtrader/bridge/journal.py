"""Atomic, persistent ingress deduplication and observation journal."""

import hashlib
import json
import sqlite3
from pathlib import Path
from threading import RLock

from .event import OrderEvent


class Journal:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                event_key TEXT PRIMARY KEY, order_key TEXT NOT NULL, revision INTEGER NOT NULL,
                digest TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL,
                result TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS order_revision ON events(order_key, revision);
            CREATE TABLE IF NOT EXISTS observations (
                observation_id INTEGER PRIMARY KEY, received_at TEXT NOT NULL,
                source_path TEXT NOT NULL, byte_offset INTEGER NOT NULL, payload TEXT NOT NULL
            );
        """)
        self.lock = RLock()

    def close(self):
        self.db.close()

    def record(self, event: OrderEvent, received_at: str, decide):
        payload = event.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        event_key = json.dumps(
            (event.source_machine, event.strategy_instance, event.account_id, event.event_id)
        )
        order_key = json.dumps(event.order_key())
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute(
                "SELECT digest, result FROM events WHERE event_key=?", (event_key,)
            ).fetchone()
            if old:
                if old[0] != digest:
                    return {
                        "mode": "shadow",
                        "ready_for_execution": False,
                        "status": "held",
                        "reason": "event_id_payload_conflict",
                    }
                return {**json.loads(old[1]), "duplicate": True}
            last = self.db.execute(
                "SELECT MAX(revision) FROM events WHERE order_key=?", (order_key,)
            ).fetchone()[0]
            if last is not None and (event.revision <= last or event.action == "CREATE"):
                result = {
                    "mode": "shadow",
                    "ready_for_execution": False,
                    "status": "held",
                    "reason": "stale_revision_or_repeated_create",
                }
            else:
                result = decide()
            result = {
                **result,
                "event_id": event.event_id,
                "bridge_received_at": received_at,
                "broker_request_started_at": None,
                "broker_response_received_at": None,
                "broker_order_id": None,
            }
            self.db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                (event_key, order_key, event.revision, digest, received_at, payload, json.dumps(result)),
            )
            return result

    def observe(self, received_at: str, source_path: str, byte_offset: int, payload: dict):
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO observations(received_at,source_path,byte_offset,payload) VALUES (?,?,?,?)",
                (received_at, source_path, byte_offset, json.dumps(payload)),
            )
