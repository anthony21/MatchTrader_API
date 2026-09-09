"""Own the selected account, read-only SDK connection and shadow capture lifecycle."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, RLock, Thread

from ..api import MatchTraderAPI
from ..bridge.api import ShadowBridge
from ..bridge.ledger import LedgerTail
from ..core.errors import APIError
from ..core.settings import Settings


class DashboardController:
    def __init__(
        self,
        settings: Settings,
        data_dir: Path,
        *,
        accounts=(),
        ledger_path: Path | None = None,
        api_factory=MatchTraderAPI,
    ):
        self.settings = settings.model_copy(update={"enable_writes": False})
        self.data_dir = data_dir
        self.ledger_path = ledger_path
        self.api_factory = api_factory
        ids = list(dict.fromkeys([settings.account_id, *accounts]))
        self.accounts = [{"id": value, "verified": False} for value in ids if value]
        if not self.accounts:
            raise ValueError("Set MTR_ACCOUNT_ID before starting the dashboard")
        self.selected = self.accounts[0]["id"]
        self.connection = "disconnected"
        self.connection_message = "Connect to verify this account and discover your other accounts."
        self.capture_message = "Stopped. Starting captures new events only."
        self.running = False
        self.api = None
        self.bridge = None
        self.orders = []
        self.orders_at = None
        self.token_message = ""
        self.lock = RLock()
        self.lifecycle = RLock()
        self.halt = Event()
        self.worker = None
        self._open_journal()

    def _open_journal(self):
        key = hashlib.sha256((self.settings.platform_url + ":" + self.selected).encode()).hexdigest()[:20]
        self.bridge = ShadowBridge(self.selected, self.data_dir / f"{key}.sqlite3")

    def _select(self, account_id):
        if account_id not in {a["id"] for a in self.accounts}:
            raise ValueError("Select a configured or broker-discovered account")
        if account_id != self.selected:
            if self.running:
                raise ValueError("Stop capture before changing accounts")
            if self.api:
                self.api.close()
                self.api = None
            self.bridge.journal.close()
            self.selected = account_id
            self.connection = "disconnected"
            self.orders = []
            self.orders_at = None
            self._open_journal()

    def connect(self, account_id):
        with self.lifecycle, self.lock:
            if self.running:
                raise ValueError("Stop capture before connecting")
            self._select(account_id)
            if self.api:
                self.api.close()
            self.api = None
            self.orders = []
            self.orders_at = None
            self.token_message = ""
            candidate = self.api_factory(self.settings.model_copy(update={"account_id": account_id}))
            try:
                auth = candidate.login()
                found = auth.tradingAccounts or auth.accounts
                if not found:
                    selected = auth.selectedTradingAccount or auth.selectedAccount
                    if selected:
                        found = [selected]
                self.accounts = [{"id": a.tradingAccountId, "verified": True} for a in found]
                self.api = candidate
                self.connection = "connected"
                self.connection_message = (
                    "Authenticated read-only connection. Broker order submission is disabled."
                )
            except Exception as exc:
                candidate.close()
                self.connection = "error"
                if isinstance(exc, APIError) and exc.status_code == 403:
                    self.connection_message = (
                        "Aqua returned HTTP 403. The Python session could not authenticate."
                    )
                else:
                    self.connection_message = (
                        "Connection failed. Check the local credentials and broker configuration."
                    )
            return self.status()

    def refresh_session(self):
        """Explicit button action: log in again on the selected account's session."""
        with self.lifecycle, self.lock:
            if not self.api:
                raise ValueError("Connect to the broker before refreshing the token")
            try:
                auth = self.api.login()
                found = auth.tradingAccounts or auth.accounts
                if not found:
                    selected = auth.selectedTradingAccount or auth.selectedAccount
                    found = [selected] if selected else []
                self.accounts = [{"id": a.tradingAccountId, "verified": True} for a in found]
                self.connection = "connected"
                self.connection_message = (
                    "Authenticated read-only connection. Broker order submission is disabled."
                )
                self.token_message = "Token refreshed successfully."
            except Exception:
                self.token_message = "Token refresh failed. Check credentials and try again."
            return self.status()

    def refresh_orders(self):
        with self.lifecycle, self.lock:
            if not self.api:
                raise ValueError("Connect to the broker before requesting active orders")
            try:
                orders = self.api.active_orders()
                fields = {
                    "id",
                    "symbol",
                    "side",
                    "type",
                    "volume",
                    "activationPrice",
                    "stopLoss",
                    "takeProfit",
                    "creationTime",
                }
                self.orders = [order.model_dump(mode="json", include=fields) for order in orders]
                self.orders_at = datetime.now(UTC).isoformat()
            except Exception:
                self.orders = []
                self.orders_at = None
                self.connection_message = "Active-order read failed. No current broker snapshot is available."
                raise ValueError(self.connection_message) from None
            return self.status()

    def start(self, account_id):
        with self.lifecycle, self.lock:
            if self.running:
                if account_id != self.selected:
                    raise ValueError("Stop capture before changing accounts")
                return self.status()
            self._select(account_id)
            tail = LedgerTail(self.ledger_path) if self.ledger_path else None
            self.halt.clear()
            self.running = True
            self.capture_message = (
                "Observing new R01 ledger rows; authenticated event receiver enabled."
                if tail
                else "Authenticated event receiver enabled; no ledger path configured."
            )
            if tail:
                self.worker = Thread(
                    target=self._watch, args=(tail,), daemon=True, name="r01-shadow-observer"
                )
                self.worker.start()
            return self.status()

    def _watch(self, tail):
        try:
            while not self.halt.wait(0.25):
                with self.lock:
                    if not self.running:
                        break
                    for offset, payload in tail.poll():
                        self.bridge.journal.observe(
                            datetime.now(UTC).isoformat(), str(tail.path), offset, payload
                        )
        except Exception:
            with self.lock:
                self.running = False
                self.capture_message = (
                    "Observation stopped after a ledger read error. Check the source and restart."
                )
        finally:
            tail.close()

    def stop(self):
        with self.lifecycle:
            with self.lock:
                self.running = False
                self.halt.set()
            if self.worker:
                self.worker.join(timeout=10)
                if self.worker.is_alive():
                    raise RuntimeError("Observer has not stopped yet")
                self.worker = None
            with self.lock:
                if self.api:
                    self.api.close()
                self.api = None
                self.token_message = ""
                self.connection = "disconnected"
                self.connection_message = "Connection closed. Existing broker orders were not changed."
                self.capture_message = "Stopped. New events are rejected until capture starts again."
                return self.status()

    def close(self):
        self.stop()
        self.bridge.journal.close()

    def receive(self, payload):
        with self.lock:
            if not self.running:
                raise ValueError("Capture is stopped")
            return self.bridge.receive(payload)

    def status(self):
        with self.lock:
            return {
                "mode": "shadow",
                "running": self.running,
                "account_id": self.selected,
                "accounts": list(self.accounts),
                "connection": self.connection,
                "connection_message": self.connection_message,
                "capture_message": self.capture_message,
                "ledger_configured": self.ledger_path is not None,
                "orders": list(self.orders),
                "orders_at": self.orders_at,
                "broker_orders_sent": 0,
                "token_expires_at": self.api.connection.session_expires_at if self.api else None,
                "token_refresh_available": self.api is not None,
                "token_message": self.token_message,
                "server_time": datetime.now(UTC).isoformat(),
            }

    def feed(self):
        with self.lock, self.bridge.journal.lock:
            db = self.bridge.journal.db
            events = db.execute(
                "SELECT received_at,payload,result FROM events ORDER BY rowid DESC LIMIT 200"
            ).fetchall()
            observations = db.execute(
                "SELECT observation_id,received_at,payload FROM observations "
                "ORDER BY observation_id DESC LIMIT 200"
            ).fetchall()
            rows = []
            for received, raw, result in events:
                event, decision = json.loads(raw), json.loads(result)
                rows.append(
                    {
                        "id": "event:" + event["event_id"],
                        "emitted_at": event["emitted_at"],
                        "received_at": received,
                        "symbol": event["instrument"],
                        "side": event["side"],
                        "action": event["action"],
                        "volume": event["volume_lots"],
                        "price": event["price"],
                        "sl": event["sl_price"],
                        "tp": event["tp_price"],
                        "status": decision["status"],
                        "reason": decision.get("reason", "Request preview only"),
                        "broker_order_id": None,
                        "order_type": event["order_type"],
                        "source_order_id": event["source_order_id"],
                    }
                )
            for identity, received, raw in observations:
                payload = json.loads(raw)
                event = payload["record"]
                rows.append(
                    {
                        "id": f"ledger:{identity}",
                        "emitted_at": event.get("utc"),
                        "received_at": received,
                        "symbol": event.get("symbol"),
                        "side": event.get("side"),
                        "action": event.get("kind"),
                        "volume": None,
                        "price": event.get("entry"),
                        "sl": event.get("sl"),
                        "tp": event.get("tp"),
                        "status": "observation",
                        "reason": payload["reason"],
                        "broker_order_id": None,
                        "order_type": None,
                        "source_order_id": event.get("label"),
                    }
                )
            rows.sort(key=lambda row: row["received_at"], reverse=True)
            return {"account_id": self.selected, "events": rows[:200]}
