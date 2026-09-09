import json
from types import SimpleNamespace

import pytest

from matchtrader.core.errors import APIError
from matchtrader.dashboard.controller import DashboardController
from matchtrader.models.account import Account
from matchtrader.models.order import Order


class FakeAPI:
    def __init__(self, settings):
        assert not settings.enable_writes
        self.closed = False

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
