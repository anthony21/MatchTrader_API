"""Publish a trade to TradingBox PAMM only after the broker read-back has verified it.

The sequence is Aqua, then verify, then publish - never simultaneous. TradingBox is a
third viewpoint, not an authority: it is told about a trade only once classify() reports
verified_open or verified_closed, its answer is written to pamm_publications and nothing
else happens. A failed publication never touches the trade, its evidence or its verified
classification, and it is never retried automatically - the attempt row itself is what
blocks a retry. Transport is the forwarder's own send (send_once by default) against its
validated URL and its authentication header; no second HTTP path exists. Publishing is
off unless the forwarder is enabled AND live with a configured URL and key.
"""

import json
from datetime import UTC, datetime
from time import monotonic

from .tradingbox_forwarder import validate_url
from .verified import classify

VERIFIED_STATES = frozenset({"verified_open", "verified_closed"})
IN_FLIGHT = "dispatching"


def is_published(row):
    """A publication counts only on a 2xx upstream status; anything else is an attempt."""
    status = row.get("upstream_status") if row else None
    return isinstance(status, int) and 200 <= status < 300


class PammPublisher:
    def __init__(self, store, forwarder_getter):
        self.store = store
        self.forwarder_getter = forwarder_getter

    def enabled(self):
        forwarder = self.forwarder_getter()
        if forwarder is None:
            return False
        _, enabled, live = forwarder.ticket()
        return bool(enabled and live and forwarder.url and forwarder.api_key)

    def publications(self, trade_ids):
        """Latest publication row per trade, for the given ids only (one query)."""
        ids = [i for i in dict.fromkeys(trade_ids) if i]
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        with self.store.lock:
            rows = self.store.db.execute(
                f"SELECT * FROM pamm_publications WHERE trade_id IN ({marks}) ORDER BY published_at",
                ids,
            ).fetchall()
        return {row["trade_id"]: dict(row) for row in rows}

    @staticmethod
    def payload(snapshot, verdict):
        read_back = verdict.get("read_back") or {}
        links = snapshot.get("links", [])
        return {
            "origin": "matchtrader-v4", "kind": "verified_trade", "trade_id": snapshot["trade_id"],
            "state": verdict["state"], "verified": True,
            "symbol": snapshot.get("symbol", ""), "side": snapshot.get("side", ""),
            "lots": snapshot.get("lots", ""), "source": snapshot.get("source", "UNKNOWN"),
            "destination_position_ids": [link["native_id"] for link in links
                                         if link["side"] == "destination" and link["kind"] == "position"],
            "broker_open_time": verdict.get("broker_open_time"),
            "broker_open_time_millis": verdict.get("broker_open_time_millis"),
            "read_back": {"reader": read_back.get("reader"), "volume": read_back.get("volume"),
                          "open_price": read_back.get("open_price")} if read_back else None,
        }

    def publish(self, snapshot, verdict=None):
        """Publish one trade if, and only if, it is verified, unpublished and publishing is on.
        Returns the recorded row, or None when nothing was attempted."""
        verdict = verdict or classify(snapshot)
        if not verdict["verified"] or verdict["state"] not in VERIFIED_STATES:
            return None
        trade_id = snapshot["trade_id"]
        if self.publications([trade_id]) or not self.enabled():
            return None
        forwarder = self.forwarder_getter()
        url = validate_url(forwarder.url)
        headers = [(forwarder.auth_header, forwarder.api_key), ("Content-Type", "application/json")]
        body = json.dumps(self.payload(snapshot, verdict), default=str).encode()
        published_at = datetime.now(UTC).isoformat()
        # Reserve the attempt before the wire, like every other write here: a crash mid-send
        # leaves a row that blocks any automatic retry instead of a silent second publish.
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT INTO pamm_publications VALUES(?,?,NULL,NULL,?)",
                                  (trade_id, published_at, IN_FLIGHT))
        started = monotonic()
        try:
            status, _reason, _headers, _payload = forwarder.send(url, headers, body)
            upstream_status, error_class = int(status), ""
        except Exception as exc:
            upstream_status, error_class = None, type(exc).__name__
        duration = round((monotonic() - started) * 1000, 3)
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "UPDATE pamm_publications SET upstream_status=?,duration_ms=?,error_class=? "
                "WHERE trade_id=? AND published_at=?",
                (upstream_status, duration, error_class, trade_id, published_at),
            )
        self.store.notify_stream()
        return {"trade_id": trade_id, "published_at": published_at, "upstream_status": upstream_status,
                "duration_ms": duration, "error_class": error_class}

    def sweep(self, snapshots):
        """Publish every newly verified trade among the given snapshots. Cheap when off."""
        if not self.enabled():
            return []
        return [row for row in (self.publish(snapshot) for snapshot in snapshots) if row]
