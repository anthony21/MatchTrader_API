import base64
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from matchtrader.core.errors import APIError
from matchtrader.dashboard.controller import DashboardController
from matchtrader.models.account import Account
from matchtrader.models.order import Order


class FakeAPI:
    def __init__(self, settings):
        assert not settings.enable_writes
        self.closed = False
        self.connection = SimpleNamespace(session_expires_at="2027-01-15T08:00:00+00:00")

    def login(self):
        return SimpleNamespace(
            tradingAccounts=[Account(tradingAccountId="123"), Account(tradingAccountId="456")]
        )

    def close(self):
        self.closed = True

    def active_orders(self):
        return [
            Order(
                id="broker-test",
                symbol="XAUUSD",
                side="SELL",
                type="LIMIT",
                volume="0.02",
                activationPrice="2400",
                unexpectedSecret="never-expose",
            )
        ]

    def open_positions(self):
        from matchtrader.models.position import Position

        return [
            Position(
                id="p1",
                symbol="EURUSD",
                side="BUY",
                volume=".01",
                openPrice="1.15",
                profit="-1.5",
                privateField="do-not-expose",
            )
        ]


def test_connect_discovers_accounts_and_stop_closes_owner(settings, tmp_path):
    controller = DashboardController(settings, tmp_path, api_factory=FakeAPI)
    try:
        assert not controller.status()["running"]
        status = controller.connect("123")
        assert status["accounts"] == [{"id": "123", "verified": True}, {"id": "456", "verified": True}]
        api = controller.api
        status = controller.refresh_orders()
        assert status["orders"][0]["id"] == "broker-test"
        assert "never-expose" not in json.dumps(status)
        status = controller.refresh_positions()
        assert status["positions"][0]["id"] == "p1" and status["positions_at"]
        assert "do-not-expose" not in json.dumps(status)
        with pytest.raises(ValueError):
            controller.set_copying(True)
        controller.stop()
        assert api.closed
        assert controller.status()["connection"] == "disconnected"
    finally:
        controller.close()


def test_connection_error_does_not_expose_upstream_body(settings, tmp_path):
    class FailedAPI(FakeAPI):
        def login(self):
            raise APIError("upstream-sensitive-body", 403)

    controller = DashboardController(settings, tmp_path, api_factory=FailedAPI)
    try:
        status = controller.connect("123")
        assert status["connection"] == "error" and "403" in status["connection_message"]
        assert "upstream-sensitive-body" not in json.dumps(status)
        assert controller.api is None
    finally:
        controller.close()


def test_start_stop_and_account_switch_isolate_journals(settings, tmp_path):
    controller = DashboardController(settings, tmp_path, accounts=["456"])
    try:
        with pytest.raises(ValueError, match="stopped"):
            controller.receive({})
        controller.start("123")
        controller.bridge.journal.observe(
            "2026-09-09T00:00:00Z",
            "ledger",
            1,
            {"record": {"kind": "touched", "symbol": "XAUUSD"}, "reason": "no volume"},
        )
        assert controller.feed()["events"][0]["status"] == "observation"
        with pytest.raises(ValueError, match="Stop"):
            controller.start("456")
        controller.stop()
        controller.start("456")
        assert controller.feed()["events"] == []
        controller.stop()
        controller.start("123")
        assert len(controller.feed()["events"]) == 1
        with pytest.raises(ValueError):
            controller.start("unknown")
    finally:
        controller.close()


def test_unknown_account_and_orders_without_connection_rejected(settings, tmp_path):
    controller = DashboardController(settings, tmp_path)
    try:
        with pytest.raises(ValueError):
            controller.connect("unknown")
        with pytest.raises(ValueError):
            controller.refresh_orders()
    finally:
        controller.close()


def test_bad_ledger_does_not_mark_capture_running(settings, tmp_path):
    controller = DashboardController(settings, tmp_path, ledger_path=tmp_path / "missing.csv")
    try:
        with pytest.raises(FileNotFoundError):
            controller.start("123")
        assert not controller.running
    finally:
        controller.close()


def test_refresh_button_relogs_same_account_and_updates_subsequent_requests(
    api_factory, auth, settings, tmp_path
):
    calls = 0
    tokens = []

    def handler(request):
        nonlocal calls
        if request.url.path.endswith("mtr-login"):
            calls += 1
            data = copy.deepcopy(auth)
            encoded = base64.urlsafe_b64encode(json.dumps({"exp": 1800000000 + calls * 3600}).encode())
            token = "header." + encoded.decode().rstrip("=") + ".signature"
            tokens.append(token)
            data["token"] = token
            data["tradingAccounts"][0]["tradingApiToken"] = f"trading-{calls}"
            return httpx.Response(200, json=data)
        if request.url.path.endswith("active-orders"):
            return httpx.Response(200, json={"orders": []})

    api, seen = api_factory(handler, settings.model_copy(update={"enable_writes": False}))
    controller = DashboardController(settings, tmp_path, api_factory=lambda settings: api)
    try:
        old = controller.connect("123")["token_expires_at"]
        controller.start("123")
        journal = controller.bridge.journal
        refreshed = controller.refresh_session()
        assert refreshed["running"] and refreshed["account_id"] == "123"
        assert controller.api is api and controller.bridge.journal is journal
        assert refreshed["token_expires_at"] != old
        assert refreshed["token_message"] == "Token refreshed successfully."
        assert calls == 2
        assert all("refresh-token" not in r.url.path for r in seen)
        controller.refresh_orders()
        assert seen[-1].headers["Cookie"] == "co-auth=" + tokens[-1]
        assert seen[-1].headers["Auth-trading-api"] == "trading-2"
        assert all(token not in json.dumps(refreshed) for token in tokens)
        controller.stop()
        assert controller.status()["token_expires_at"] is None
    finally:
        controller.close()


def test_failed_manual_refresh_preserves_expiry_and_reports_sanitized_error(settings, tmp_path):
    controller = DashboardController(settings, tmp_path, api_factory=FakeAPI)
    try:
        with pytest.raises(ValueError, match="Connect"):
            controller.refresh_session()
        before = controller.connect("123")

        def fail():
            raise APIError("secret-response")

        controller.api.login = fail
        after = controller.refresh_session()
        assert after["token_expires_at"] == before["token_expires_at"]
        assert "failed" in after["token_message"]
        assert "secret-response" not in json.dumps(after)
    finally:
        controller.close()
