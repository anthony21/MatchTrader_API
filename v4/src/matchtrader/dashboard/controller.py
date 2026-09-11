"""Own the selected account, read-only SDK connection and shadow capture lifecycle."""

import hashlib
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic

from ..api import MatchTraderAPI
from ..bridge.api import ShadowBridge
from ..bridge.ledger import LedgerTail
from ..capture.logging_store import LoggingStore
from ..capture.meaning import meaning
from ..capture.reconcile import reconcile
from ..capture.relay_store import RelayLogStore
from ..capture.router import CaptureRouter
from ..capture.store import CaptureStore
from ..core.errors import APIError
from ..core.settings import Settings
from ..version import EVENT_SCHEMA_VERSION, MAPPING_SCHEMA_VERSION, VERSION
from .copy_settings import CopySettings, load_settings, save_settings


class DashboardController:
    def __init__(
        self,
        settings: Settings,
        data_dir: Path,
        *,
        accounts=(),
        ledger_path: Path | None = None,
        api_factory=MatchTraderAPI,
        route=None,
        csv_limit=1000,
        interactive_copying=False,
    ):
        saved = load_settings(data_dir / "copy-settings.json")
        if saved and route is None:
            route, csv_limit = saved.route, saved.csv_limit
        self.interactive_copying = interactive_copying
        self.settings = settings.model_copy(
            update={"enable_writes": route is not None or interactive_copying}
        )
        self.data_dir = data_dir
        self.ledger_path = ledger_path
        self.api_factory = api_factory
        ids = list(dict.fromkeys([settings.account_id, *accounts]))
        self.accounts = [{"id": value, "verified": False} for value in ids if value]
        self.selected = self.accounts[0]["id"] if self.accounts else ''
        self.connection = "disconnected"
        self.connection_message = "Connect to verify this account and discover your other accounts."
        self.capture_message = "Stopped. Starting captures new events only."
        self.running = False
        self.capture_generation = 0
        self.capture_websocket = None
        self.api = None
        self.broker_profiles = None
        self.tradingbox_forwarder = None
        self.bridge = None
        self.orders = []
        self.orders_at = None
        self.positions = []
        self.positions_at = None
        self.native_store = CaptureStore(data_dir / "quantower", csv_limit, broker=settings.platform_url, background_exports=True)
        self.native = CaptureRouter(self.native_store, route)
        self.relay_logs = RelayLogStore(data_dir / 'relay')
        self.logging_events = LoggingStore(data_dir / 'logging')
        self.token_message = ""
        self.reconciliation_message = ""
        self.lock = RLock()
        self.lifecycle = RLock()
        self.halt = Event()
        self.worker = None
        self._open_journal()

    def _open_journal(self):
        if not self.selected:
            return
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
            if self.bridge:
                self.bridge.journal.close()
            self.selected = account_id
            self.connection = "disconnected"
            self.orders = []
            self.orders_at = None
            self.positions = []
            self.positions_at = None
            self.native.armed = False
            self._open_journal()

    def connect(self, account_id, *, authentication=None):
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
            self.positions = []
            self.positions_at = None
            self.native.armed = False
            self.native.demo_verified = False
            overrides = {"account_id": account_id}
            if account_id != self.settings.account_id:
                overrides.update(system_uuid='', ws_url='', ws_headers_json='{}', ws_subprotocol='')
            candidate = self.api_factory(self.settings.model_copy(update=overrides))
            try:
                auth = candidate.use_login(authentication) if authentication is not None else candidate.login()
                found = auth.tradingAccounts or auth.accounts
                if not found:
                    selected = auth.selectedTradingAccount or auth.selectedAccount
                    if selected:
                        found = [selected]
                self.accounts = [{"id": a.tradingAccountId, "verified": True} for a in found]
                self.api = candidate
                self.native.demo_verified = any(
                    a.tradingAccountId == account_id and a.offer.get("demo") is True for a in found
                )
                self.connection = "connected"
                self.connection_message = (
                    "Connected. Copying is enabled."
                    if self.native.armed
                    else "Connected. Copying is disabled."
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

    def refresh_positions(self):
        with self.lifecycle, self.lock:
            if not self.api:
                raise ValueError("Connect before requesting open positions")
            try:
                positions = self.native._positions(self.api.open_positions())
                fields = {
                    "id",
                    "symbol",
                    "side",
                    "volume",
                    "openPrice",
                    "stopLoss",
                    "takeProfit",
                    "profit",
                    "netProfit",
                    "openTime",
                    "openTimeMillis",
                }
                self.positions = [p.model_dump(mode="json", include=fields) for p in positions]
                self.positions_at = datetime.now(UTC).isoformat()
                with self.native.lock:
                    reconcile(self.native_store, self.api, self.selected, positions)
            except Exception:
                self.positions = []
                self.positions_at = None
                raise ValueError("Open-position read failed; no current snapshot available") from None
            return self.status()

    def set_copying(self, enabled):
        with self.lifecycle, self.lock, self.native.lock:
            if not isinstance(enabled, bool):
                raise ValueError("Enabled must be a boolean")
            route = self.native.route
            if enabled and not (
                self.running
                and self.api
                and route
                and self.native.demo_verified
                and route.destination_account == self.selected
            ):
                raise ValueError("Configure a source route and connect the demo destination first")
            self.native.armed = enabled
            self.native.armed_at = datetime.now(UTC) if enabled else None
            self.connection_message = (
                "Connected. Copying enabled for the configured demo route."
                if enabled
                else "Connected. Copying is disabled."
            )
            return self.status()

    def copy_settings(self):
        with self.lock:
            # Inventory survives the feed's 200-event window.
            rows = self.native_store.db.execute(
                "SELECT payload FROM events WHERE json_extract(payload, '$.kind')='ACCOUNT' ORDER BY seq"
            ).fetchall()
            inventory = {}
            for row in rows:
                event = json.loads(row[0])
                key = (event["machine"], event["connection_id"], event["account_id"])
                inventory[key] = {k: event[k] for k in ("machine", "connection_id", "account_id", "status")}
            return {
                "route": self.native.route.model_dump(mode="json") if self.native.route else None,
                "csv_limit": self.native_store.limit,
                "inventory": list(inventory.values()),
            }

    def configure_copying(self, payload):
        value = CopySettings.model_validate(payload)
        with self.lifecycle, self.lock, self.native.lock:
            if not self.interactive_copying:
                raise ValueError("Interactive settings are not enabled")
            if self.native.armed:
                raise ValueError("Stop copying before changing settings")
            if self.native.route and self.native.route != value.route:
                active = self.native_store.db.execute(
                    "SELECT count(*) FROM trades WHERE destination!='' AND state!='resolved'"
                ).fetchone()[0]
                if active:
                    raise ValueError("Resolve existing copied trades before changing their route")
            save_settings(self.data_dir / "copy-settings.json", value)
            self.native.route = value.route
            self.native_store.limit = value.csv_limit
            self.native_store.export()
            return self.copy_settings()

    def receive_native(self, payload, *, capture_generation=None):
        with self.lock:
            if not self.running or (capture_generation is not None and capture_generation != self.capture_generation):
                raise ValueError("Capture is stopped")
            return self.native.receive(payload, self.api, self.selected)

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
                self.native.demo_verified = any(
                    a.tradingAccountId == self.selected and a.offer.get("demo") is True for a in found
                )
                if not self.native.demo_verified:
                    self.native.armed = False
                self.connection = "connected"
                self.connection_message = (
                    "Connected. Copying is enabled."
                    if self.native.armed
                    else "Connected. Copying is disabled."
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
                    "creationTimeIso",
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
            self.capture_generation += 1
            self.running = True
            self.capture_message = (
                "Native event receiver enabled; also observing new R01 CSV rows."
                if tail
                else "Authenticated event receiver enabled; no ledger path configured."
            )
            self.worker = Thread(target=self._watch, args=(tail,), daemon=True, name="capture-observer")
            self.worker.start()
            return self.status()

    def _watch(self, tail):
        next_reconcile = monotonic() + 15
        try:
            while not self.halt.wait(0.25):
                with self.lock:
                    if not self.running:
                        break
                    for offset, payload in tail.poll() if tail else ():
                        self.bridge.journal.observe(
                            datetime.now(UTC).isoformat(), str(tail.path), offset, payload
                        )
                    if self.api and self.native.route and monotonic() >= next_reconcile:
                        next_reconcile = monotonic() + 15
                        try:
                            with self.native.lock:
                                reconcile(
                                    self.native_store, self.api, self.selected, self.api.open_positions()
                                )
                            self.reconciliation_message = ""
                        except Exception:
                            self.reconciliation_message = (
                                "Broker reconciliation unavailable; unresolved IDs retained."
                            )
        except Exception:
            with self.lock:
                self.running = False
                self.native.armed = False
                self.capture_message = (
                    "Observation stopped after a ledger read error. Check the source and restart."
                )
        finally:
            if tail:
                tail.close()

    def stop(self):
        with self.lifecycle:
            with self.lock:
                self.running = False
                self.native.armed = False
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
        if self.tradingbox_forwarder:
            self.tradingbox_forwarder.close()
        if self.broker_profiles:
            self.broker_profiles.close()
        if self.capture_websocket:
            self.capture_websocket.close()
        self.stop()
        if self.bridge:
            self.bridge.journal.close()
        self.native_store.close()
        self.relay_logs.close()
        self.logging_events.close()

    def receive(self, payload):
        with self.lock:
            if not self.running:
                raise ValueError("Capture is stopped")
            return self.bridge.receive(payload)

    def status(self):
        with self.lock:
            return {
                "mode": "copying" if self.native.armed else "capture",
                "version": VERSION,
                "relay_logs": self.relay_logs.status(),
                "tradingbox_forwarding": self.tradingbox_forwarder.status() if self.tradingbox_forwarder else {"enabled": False, "live": False},
                "capture_websocket": self.capture_websocket.status() if self.capture_websocket else {"listening": False},
                "event_schema_version": EVENT_SCHEMA_VERSION,
                "mapping_schema_version": MAPPING_SCHEMA_VERSION,
                "running": self.running,
                "account_id": self.selected,
                "accounts": list(self.accounts),
                "connection": self.connection,
                "connection_message": self.connection_message,
                "capture_message": self.capture_message,
                "ledger_configured": self.ledger_path is not None,
                "orders": list(self.orders),
                "orders_at": self.orders_at,
                "positions": list(self.positions),
                "positions_at": self.positions_at,
                "copying": self.native.armed,
                "route_configured": self.native.route is not None,
                "csv_export_error": self.native_store.export_error,
                "reconciliation_message": self.reconciliation_message,
                "broker_orders_sent": self.native_store.db.execute(
                    "SELECT count(*) FROM trades WHERE destination=? "
                    "AND (broker_order_id!='' OR broker_position_id!='')",
                    (self.selected,),
                ).fetchone()[0],
                "token_expires_at": self.api.connection.session_expires_at if self.api else None,
                "token_refresh_available": self.api is not None,
                "token_message": self.token_message,
                "server_time": datetime.now(UTC).isoformat(),
            }

    def feed(self):
        with self.lock, (self.bridge.journal.lock if self.bridge else nullcontext()):
            if self.bridge is None:
                return {'account_id': '', 'events': []}
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
                        "account_id": event["account_id"],
                        "machine": event["source_machine"],
                        "connection_id": "legacy",
                        "kind": "LEGACY",
                        "source": "UNKNOWN",
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
                        "account_id": "",
                        "machine": "ledger",
                        "connection_id": "R01 CSV",
                        "kind": "LEDGER",
                        "source": "R01",
                    }
                )
            rows.sort(key=lambda row: row["received_at"], reverse=True)
            for row in rows:
                row['quantity'] = row['volume']
                row['quantity_unit'] = 'lots' if row['kind'] == 'LEGACY' else 'UNKNOWN'
                row['order_id'] = row['source_order_id']
                row['meaning'] = meaning({**row, 'decision': row['status']})
            return {"account_id": self.selected, "events": rows[:200]}
