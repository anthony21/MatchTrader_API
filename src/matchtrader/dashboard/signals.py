"""Unauthenticated local raw-signal journal and WebSocket fan-out; no broker dispatch."""

import json
import sqlite3
from datetime import UTC, datetime
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
from urllib.parse import parse_qs, urlsplit

from websockets.exceptions import ConnectionClosed
from websockets.protocol import State
from websockets.sync.server import serve

from ..signal_parsing import default_engine

MAX_SIGNAL = 65536


class SignalHub:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL)"
        )
        self.subscribers = set()
        self.parser = default_engine()

    def recent(self):
        with self.lock:
            rows = self.db.execute("SELECT event FROM signals ORDER BY id DESC LIMIT 200").fetchall()
            return [json.loads(row[0]) for row in reversed(rows)]

    def publish(self, raw, source=""):
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str) or not raw.strip() or len(raw.encode("utf-8")) > MAX_SIGNAL:
            raise ValueError("Send a nonempty UTF-8 signal up to 64 KiB")
        try:
            payload = json.loads(raw)
            json.dumps(payload, allow_nan=False)
            parsed = True
        except (ValueError, RecursionError):
            payload, parsed = None, False
        fields = payload if isinstance(payload, dict) else {}

        def label(*keys, default=""):
            value = next((fields[key] for key in keys if fields.get(key) not in (None, "")), default)
            return str(value)[:200] if isinstance(value, (str, int, float)) else default

        event = {
            "received_at": datetime.now(UTC).isoformat(),
            "raw": raw,
            "payload": payload,
            "parsed": parsed,
            "source": label("source", "strategy", "sending_source", default=source or "UNKNOWN"),
            "kind": label("kind", "event_type", "eventType", "type", default="SIGNAL"),
            "symbol": label("symbol", "instrument"),
            "account_id": label("account_id", "accountId"),
            "event_id": label("event_id", "eventId"),
            "action": label("action"),
            "signals": [result.record() for result in self.parser.parse_raw(raw)],
        }
        with self.lock:
            with self.db:
                cursor = self.db.execute("INSERT INTO signals(event) VALUES (?)", ("{}",))
                event["id"] = cursor.lastrowid
                self.db.execute("UPDATE signals SET event=? WHERE id=?", (json.dumps(event), event["id"]))
                self.db.execute("DELETE FROM signals WHERE id <= ?", (event["id"] - 2000,))
            # Commit before publishing; serialize fan-out by journal ID.
            for queue in self.subscribers:
                try:
                    queue.put_nowait({"type": "signal", "event": event})
                except Full:
                    while True:
                        try:
                            queue.get_nowait()
                        except Empty:
                            break
                    queue.put_nowait({"type": "snapshot", "events": self.recent()})
        return {"status": "received", "id": event["id"], "event_id": event["event_id"], "parsed": parsed}

    def subscribe(self):
        with self.lock:
            queue = Queue(maxsize=256)
            self.subscribers.add(queue)
            queue.put({"type": "snapshot", "events": self.recent()})
            return queue

    def unsubscribe(self, queue):
        with self.lock:
            self.subscribers.discard(queue)

    def close(self):
        with self.lock:
            self.db.close()


class SignalServer:
    def __init__(self, hub, port=8766):
        self.hub = hub
        self.halt = Event()
        self.lock = RLock()
        self.connections = set()
        self.idle = Event()
        self.idle.set()
        self.server = serve(
            self.handle,
            "127.0.0.1",
            port,
            max_size=MAX_SIGNAL,
            compression=None,
            close_timeout=1,
            ping_interval=20,
            ping_timeout=20,
        )
        self.port = self.server.socket.getsockname()[1]
        self.thread = Thread(target=self.server.serve_forever, name="signal-websocket", daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.halt.set()
        self.server.shutdown()
        with self.lock:
            connections = list(self.connections)
        for connection in connections:
            connection.close(1001, "Application shutting down")
        self.thread.join(timeout=5)
        self.idle.wait(timeout=5)

    def handle(self, connection):
        queue = None
        with self.lock:
            if self.halt.is_set():
                connection.close(1001, "Application shutting down")
                return
            self.connections.add(connection)
            self.idle.clear()
        try:
            url = urlsplit(connection.request.path)
            if url.path == "/signals":
                source = parse_qs(url.query).get("source", [""])[0][:200]
                for raw in connection:
                    try:
                        result = self.hub.publish(raw, source)
                    except (ValueError, UnicodeError):
                        result = {"status": "rejected", "error": "Send a nonempty UTF-8 signal up to 64 KiB"}
                    connection.send(json.dumps(result))
            elif url.path == "/events":
                queue = self.hub.subscribe()
                while not self.halt.is_set() and connection.state is State.OPEN:
                    try:
                        message = queue.get(timeout=0.25)
                    except Empty:
                        continue
                    connection.send(json.dumps(message))
            else:
                connection.close(1008, "Use /signals to publish or /events to subscribe")
        except ConnectionClosed:
            pass
        finally:
            if queue is not None:
                self.hub.unsubscribe(queue)
            with self.lock:
                self.connections.discard(connection)
                if not self.connections:
                    self.idle.set()
