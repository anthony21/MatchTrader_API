import base64
import copy
import json

import httpx
import pytest

from matchtrader.dashboard.broker_dashboard import BrokerDashboard
from matchtrader.sessions.matchtrader_adapter import MatchTraderAdapter
from matchtrader.sessions.profiles import BrokerProfile
from matchtrader.sessions.session_manager import SessionManager


def test_dashboard_switches_brokers_without_relogin_or_shared_journals(settings, auth, tmp_path, monkeypatch):
    logins = []
    profiles = [
        BrokerProfile(
            key,
            key,
            settings.model_copy(
                update={
                    "platform_url": f"https://{key.lower()}.example",
                    "account_id": "123" if key == "AQUA" else "",
                }
            ),
        )
        for key in ("AQUA", "GTR")
    ]

    def factory(config, **options):
        payload = copy.deepcopy(auth)
        encoded = base64.urlsafe_b64encode(json.dumps({"exp": 1900}).encode()).decode().rstrip("=")
        payload["token"] = f"x.{encoded}.x"
        second = copy.deepcopy(payload["tradingAccounts"][0])
        second["tradingAccountId"] = "456"
        payload["tradingAccounts"].append(second)

        def handle(request):
            if request.url.path == "/manager/mtr-login":
                logins.append(request.url.host)
                return httpx.Response(200, json=payload)
            if request.url.path == "/manager/refresh-token":
                expiry = base64.urlsafe_b64encode(json.dumps({"exp": 2800}).encode()).decode().rstrip("=")
                return httpx.Response(200, json={"token": f"x.{expiry}.x"})
            return httpx.Response(200, json={"orders": []})

        return MatchTraderAdapter(config, transport_factory=lambda: httpx.MockTransport(handle), **options)

    manager = SessionManager(clock=lambda: 1000, automatic=False)
    app = BrokerDashboard(profiles, tmp_path, manager=manager, adapter_factory=factory)
    try:
        assert app.connect("123")["connection"] == "connected"
        aqua_journal = app.current.bridge.journal
        app.select_broker("GTR")
        assert app.status()["account_id"] == ""
        assert app.feed()["events"] == []
        assert app.connect("")["connection"] == "connected"
        assert app.current.bridge.journal is not aqua_journal
        assert app.current.native_store is not app.controllers["AQUA"].native_store
        assert len(logins) == 2
        app.connect("456")
        assert len(logins) == 2
        assert app.status()["account_id"] == "456"
        assert app.refresh_orders()["orders"] == []
        app.select_broker("AQUA")
        assert app.status()["connection"] == "connected"
        assert all(b["state"] == "connected" for b in app.status()["brokers"])
        app.start("123")
        owner = app.current
        monkeypatch.setattr(
            owner, "receive_native", lambda payload: {"destination": "AQUA", "payload": payload}
        )
        monkeypatch.setattr(owner, "receive", lambda payload: {"destination": "AQUA"})
        app.select_broker("GTR")
        assert owner.running
        assert app.status()["capture_broker_id"] == "AQUA"
        previous_expiry = manager.status("AQUA")["expires_at"]
        other_expiry = manager.status("GTR")["expires_at"]
        manager.refresh("AQUA")
        assert manager.status("AQUA")["expires_at"] != previous_expiry
        assert manager.status("GTR")["expires_at"] == other_expiry
        assert app.status()["broker_id"] == "GTR"
        assert app.receive_native({"test": True})["destination"] == "AQUA"
        assert app.receive({})["destination"] == "AQUA"
        with pytest.raises(ValueError):
            app.start("456")
        app.select_broker("AQUA")
        handle = app.current.api
        expiry = manager.status("AQUA")["expires_at"]
        app.stop()
        assert app.current.api is handle and not handle.closed
        assert manager.status("AQUA")["expires_at"] == expiry
        assert manager.status("AQUA")["state"] == "connected"
        assert app.refresh_orders()["connection"] == "connected"
        assert len(logins) == 2
        app.disconnect_broker("AQUA")
        assert manager.status("AQUA")["state"] == "disconnected"
        assert manager.status("GTR")["state"] == "connected"
    finally:
        app.close()
    assert all(s["state"] == "disconnected" for s in manager.status())
