"""Broker-scoped dashboard workspaces sharing one application session manager."""

from functools import partial
from threading import RLock

from ..sessions.matchtrader_adapter import AccountSession, MatchTraderAdapter
from ..sessions.session_manager import SessionManager
from .controller import DashboardController


class BrokerDashboard:
    def __init__(
        self,
        profiles,
        data_dir,
        *,
        manager=None,
        adapter_factory=MatchTraderAdapter,
        accounts=(),
        ledger_path=None,
        route=None,
        csv_limit=1000,
    ):
        self.manager = manager or SessionManager()
        self.lock = RLock()
        self.controllers = {}
        self.selected_broker = profiles[0].key
        try:
            for index, profile in enumerate(profiles):
                # The legacy route belongs only to the primary broker, even when
                # two brokers expose identical account numbers.
                broker_route = route if index == 0 else None
                settings = profile.settings.model_copy(update={"enable_writes": broker_route is not None})
                self.manager.register(
                    profile.key,
                    profile.label,
                    adapter_factory(settings, require_demo=True, transport_settings=profile.transport),
                )
                self.controllers[profile.key] = DashboardController(
                    settings,
                    data_dir if index == 0 else data_dir / "brokers" / profile.key,
                    accounts=accounts if index == 0 else (),
                    ledger_path=ledger_path,
                    api_factory=partial(AccountSession, self.manager, profile.key),
                    route=broker_route,
                    csv_limit=csv_limit,
                    allow_discovery=True,
                )
        except Exception:
            self.close()
            raise

    @property
    def current(self):
        return self.controllers[self.selected_broker]

    @property
    def native_store(self):
        return self.current.native_store

    def select_broker(self, key):
        with self.lock:
            if key not in self.controllers:
                raise ValueError("Unknown broker")
            self.selected_broker = key
            return self.status()

    def disconnect_broker(self, key):
        with self.lock:
            if key not in self.controllers:
                raise ValueError("Unknown broker")
            self.controllers[key].stop()
            self.manager.disconnect(key)
            return self.status()

    def stop(self):
        with self.lock:
            self.current.stop(disconnect=False)
            return self.status()

    def start(self, account_id):
        with self.lock:
            if any(c.running for key, c in self.controllers.items() if key != self.selected_broker):
                raise ValueError("Capture is already running for another broker")
            self.current.start(account_id)
            return self.status()

    def _capture_owner(self):
        # The ingress destination is the started capture, never the broker in view.
        return next(
            (controller for controller in self.controllers.values() if controller.running), self.current
        )

    def receive(self, payload):
        with self.lock:
            return self._capture_owner().receive(payload)

    def receive_native(self, payload):
        with self.lock:
            return self._capture_owner().receive_native(payload)

    def connect(self, account_id):
        with self.lock:
            if self.current.running:
                raise ValueError("Stop capture before changing accounts")
            try:
                data = self.manager.connect(self.selected_broker)
            except Exception:
                self.current.connection = "error"
                self.current.connection_message = (
                    "Broker login failed; check local credentials and configuration"
                )
                return self.status()
            self.current.accounts = [{"id": value, "verified": True} for value in data.accounts]
            self.current.connect(account_id or self.current.selected or data.accounts[0])
            return self.status()

    def refresh_session(self):
        with self.lock:
            self.current.refresh_session()
            return self.status()

    def status(self):
        with self.lock:
            result = self.current.status()
            result["capture_broker_id"] = next(
                (key for key, c in self.controllers.items() if c.running), None
            )
            brokers = self.manager.status()
            for broker in brokers:
                controller = self.controllers[broker["id"]]
                broker["selected_account"] = controller.selected
                broker["capture_running"] = controller.running
                broker["configured_accounts"] = [a["id"] for a in controller.accounts]
            selected = next(b for b in brokers if b["id"] == self.selected_broker)
            if selected["accounts"]:
                self.current.accounts = [
                    {"id": account, "verified": True} for account in selected["accounts"]
                ]
                result["accounts"] = list(self.current.accounts)
            if self.current.api and self.current.selected not in selected["accounts"]:
                self.current.native.armed = False
                result.update(
                    connection="error",
                    connection_message="Selected account is no longer available at this broker",
                    copying=False,
                )
                result.update(
                    broker_id=self.selected_broker, brokers=brokers, token_refresh_at=selected["refresh_at"]
                )
                return result
            if self.current.api and selected["state"] != "connected":
                self.current.native.armed = False
                result.update(
                    connection=selected["state"], connection_message=selected["message"], copying=False
                )
            elif self.current.api:
                result.update(connection="connected", connection_message=selected["message"])
            result.update(
                broker_id=self.selected_broker, brokers=brokers, token_refresh_at=selected["refresh_at"]
            )
            return result

    def close(self):
        for controller in self.controllers.values():
            controller.close()
        self.manager.close()

    def __getattr__(self, name):
        if name not in {
            "start",
            "refresh_orders",
            "refresh_positions",
            "set_copying",
            "receive",
            "receive_native",
            "feed",
        }:
            raise AttributeError(name)

        def call(*args, **kwargs):
            with self.lock:
                result = getattr(self.current, name)(*args, **kwargs)
                return (
                    self.status()
                    if name in {"start", "refresh_orders", "refresh_positions", "set_copying"}
                    else result
                )

        return call
