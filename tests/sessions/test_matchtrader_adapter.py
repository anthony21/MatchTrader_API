import base64
import copy
import json

import httpx
import pytest

from matchtrader.core.base_connection import BaseConnection
from matchtrader.core.errors import AuthenticationError, ProtocolError, WritesDisabledError
from matchtrader.sessions.matchtrader_adapter import AccountSession, MatchTraderAdapter
from matchtrader.sessions.session_manager import SessionManager


def jwt(exp):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return "header." + payload + ".signature"


def test_multibroker_multiaccount_routing_and_transports_close(settings, auth):
    calls, transports = [], []
    manager = SessionManager(clock=lambda: 1000, automatic=False)

    class Transport(httpx.MockTransport):
        closed = False

        def close(self):
            self.closed = True

    def build(broker):
        config = settings.model_copy(update={"platform_url": f"https://{broker}.example"})
        data = copy.deepcopy(auth)
        data["token"] = jwt(1900)
        data["tradingAccounts"][0]["tradingApiToken"] = broker + "-123"
        second = copy.deepcopy(data["tradingAccounts"][0])
        second.update(tradingAccountId="456", tradingApiToken=broker + "-456")
        second["offer"]["system"]["uuid"] = "system-2"
        data["tradingAccounts"].append(second)

        def handle(request):
            calls.append(request)
            if request.url.path == "/manager/mtr-login":
                return httpx.Response(
                    200, json=data, headers={"set-cookie": "rt=private-refresh; Path=/manager; Secure"}
                )
            if request.url.path == "/manager/refresh-token":
                assert "rt=private-refresh" in request.headers["Cookie"]
                return httpx.Response(200, json={"token": jwt(2620)})
            return httpx.Response(200, json={"orders": []})

        def factory():
            transport = Transport(handle)
            transports.append(transport)
            return transport

        manager.register(broker, broker, MatchTraderAdapter(config, transport_factory=factory))
        return config

    aqua, gooey = build("aqua"), build("gooey")
    a1 = AccountSession(manager, "aqua", aqua)
    a2 = AccountSession(manager, "aqua", aqua.model_copy(update={"account_id": "456"}))
    g1 = AccountSession(manager, "gooey", gooey)
    for account in (a1, a2, g1):
        account.login()
        assert account.active_orders() == []
    assert sum(r.url.path == "/manager/mtr-login" for r in calls) == 2
    trades = [r for r in calls if r.url.path.endswith("active-orders")]
    assert [r.headers["Auth-trading-api"] for r in trades] == ["aqua-123", "aqua-456", "gooey-123"]
    assert trades[1].url.path.startswith("/mtr-api/system-2/")
    a1.refresh()
    a2.active_orders()
    assert calls[-1].headers["Cookie"] == "co-auth=" + jwt(2620)
    g1.active_orders()
    assert calls[-1].headers["Cookie"] == "co-auth=" + jwt(1900)
    a1.close()
    a2.active_orders()
    assert all(t.closed for t in transports)
    assert not BaseConnection._registry
    manager.close()


@pytest.mark.parametrize("token", ["opaque", jwt(True), jwt("1900"), "a.!.b"])
def test_missing_or_invalid_expiry_is_not_guessed(settings, auth, token):
    auth["token"] = token
    adapter = MatchTraderAdapter(
        settings,
        transport_factory=lambda: httpx.MockTransport(lambda request: httpx.Response(200, json=auth)),
    )
    with pytest.raises(ProtocolError):
        adapter.login()


def test_rejected_mutation_is_not_replayed_or_reauthenticated(settings, auth):
    auth["token"] = jwt(1900)
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path == "/manager/mtr-login":
            return httpx.Response(200, json=auth)
        return httpx.Response(401)

    manager = SessionManager(clock=lambda: 1000, automatic=False)
    manager.register(
        "A", "A", MatchTraderAdapter(settings, transport_factory=lambda: httpx.MockTransport(handle))
    )
    account = AccountSession(manager, "A", settings)
    account.login()
    with pytest.raises(AuthenticationError):
        account.create_pending_order(
            instrument="XAUUSD",
            orderSide="BUY",
            type="LIMIT",
            volume=1,
            price=4340,
            slPrice=4330,
            tpPrice=4350,
        )
    assert len(seen) == 2
    payload = json.loads(seen[-1].content)
    assert payload["price"] == 4340 and payload["slPrice"] == 4330 and payload["tpPrice"] == 4350
    assert manager.status("A")["state"] == "retrying"
    manager.close()


def test_write_gate_and_no_raw_transport_access(settings, auth):
    auth["token"] = jwt(1900)
    settings = settings.model_copy(update={"enable_writes": False})
    manager = SessionManager(clock=lambda: 1000, automatic=False)
    manager.register(
        "A",
        "A",
        MatchTraderAdapter(
            settings,
            transport_factory=lambda: httpx.MockTransport(lambda request: httpx.Response(200, json=auth)),
        ),
    )
    account = AccountSession(manager, "A", settings)
    account.login()
    with pytest.raises(WritesDisabledError):
        account.cancel_pending_order(instrument="XAUUSD", id="test", orderSide="BUY", type="LIMIT")
    with pytest.raises(AttributeError):
        account.websocket()
    account.close()
    with pytest.raises(RuntimeError):
        account.active_orders()
    manager.close()


@pytest.mark.parametrize("mode", ["cookie", "accounts", "rejected", "unchanged"])
def test_refresh_cookie_rotation_account_replacement_and_reauthentication(settings, auth, mode):
    now = [1000.0]
    auth["token"] = jwt(1900)
    count = {"login": 0}
    cookies = []

    def handle(request):
        if request.url.path == "/manager/mtr-login":
            count["login"] += 1
            data = copy.deepcopy(auth)
            if count["login"] > 1:
                data["token"] = jwt(2620)
            return httpx.Response(200, json=data, headers={"set-cookie": "rt=first; Path=/manager"})
        if request.url.path == "/manager/refresh-token":
            cookies.append(request.headers.get("Cookie", ""))
            if mode == "rejected":
                return httpx.Response(401)
            if mode == "cookie":
                return httpx.Response(204, headers={"set-cookie": "co-auth=" + jwt(2620) + "; Path=/"})
            if mode == "unchanged":
                return httpx.Response(200, json={"status": "OK"})
            replacement = copy.deepcopy(auth["tradingAccounts"][0])
            replacement.update(tradingAccountId="456", tradingApiToken="new-account-token")
            return httpx.Response(200, json={"token": jwt(2620), "accounts": [replacement]})
        return httpx.Response(200, json={"orders": []})

    manager = SessionManager(clock=lambda: now[0], automatic=False)
    manager.register(
        "A", "A", MatchTraderAdapter(settings, transport_factory=lambda: httpx.MockTransport(handle))
    )
    manager.connect("A")
    now[0] = 1720
    manager.renew_due()
    assert "rt=first" in cookies[0] and "co-auth=" + jwt(1900) in cookies[0]
    assert manager.status("A")["state"] == ("retrying" if mode == "unchanged" else "connected")
    if mode == "accounts":
        assert manager.status("A")["accounts"] == ["456"]
        with pytest.raises(AuthenticationError):
            manager.execute("A", "123", "active_orders")
        assert manager.execute("A", "456", "active_orders") == []
    assert count["login"] == (2 if mode == "rejected" else 1)
    manager.close()
