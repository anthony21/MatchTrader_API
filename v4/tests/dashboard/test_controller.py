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
                creationTimeIso="2026-09-10T01:37:03.439Z",
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
                netProfit="0",
                openTimeMillis=1789000000000,
                privateField="do-not-expose",
            )
        ]


def test_start_without_account_allows_discovery_but_not_capture(settings, tmp_path):
    controller = DashboardController(settings.model_copy(update={'account_id': ''}), tmp_path)
    try:
        assert controller.status()['account_id'] == ''
        assert controller.feed() == {'account_id': '', 'events': []}
        assert controller.bridge is None
        with pytest.raises(ValueError):
            controller.start('')
    finally:
        controller.close()


def test_connect_discovers_accounts_and_stop_closes_owner(settings, tmp_path):
    controller = DashboardController(settings, tmp_path, api_factory=FakeAPI)
    try:
        assert not controller.status()["running"]
        status = controller.connect("123")
        assert status["accounts"] == [{"id": "123", "verified": True}, {"id": "456", "verified": True}]
        api = controller.api
        status = controller.refresh_orders()
        assert status["orders"][0]["id"] == "broker-test"
        assert status["orders"][0]["creationTimeIso"] == "2026-09-10T01:37:03.439Z"
        assert "never-expose" not in json.dumps(status)
        status = controller.refresh_positions()
        assert status["positions"][0]["id"] == "p1" and status["positions_at"]
        assert status["positions"][0]["profit"] == "-1.5"
        assert status["positions"][0]["netProfit"] == "0"
        assert status["positions"][0]["openTimeMillis"] == 1789000000000
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


def test_position_only_broker_acceptance_counts_for_selected_account(settings, tmp_path):
    controller = DashboardController(settings, tmp_path, api_factory=FakeAPI)
    try:
        with controller.native_store.db:
            controller.native_store.db.execute(
                "INSERT INTO trades(trade_id,source_key,destination,broker_position_id) VALUES(?,?,?,?)",
                ('trade', 'source-key', '123', 'position-only'),
            )
        assert controller.status()['broker_orders_sent'] == 1
        controller.selected = '456'
        assert controller.status()['broker_orders_sent'] == 0
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
        observed = controller.feed()["events"][0]
        assert observed["status"] == "observation"
        assert observed["meaning"]["source"]["code"] == "R01"
        assert observed["meaning"]["opened"]["state"] == "unconfirmed"
        assert observed["account_id"] == ""  # CSV does not establish source account.
        assert observed["quantity"] is None
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


def test_capture_generation_rejects_queued_previous_session(settings, tmp_path):
    controller = DashboardController(settings, tmp_path)
    try:
        controller.start('123')
        generation = controller.capture_generation
        controller.stop()
        controller.start('123')
        with pytest.raises(ValueError, match='Capture is stopped'):
            controller.receive_native({}, capture_generation=generation)
    finally:
        controller.close()


class VerifiedAPI(FakeAPI):
    """A connected owner whose session names the selected account; every broker write is forbidden."""

    def __init__(self, settings):
        self.closed = False
        self.connection = SimpleNamespace(session_expires_at=None, account_id=settings.account_id)
        self.writes = []

    def create_pending_order(self, **kwargs):
        self.writes.append(kwargs)
        raise AssertionError('Disarmed signal copying must never place an order')

    open_position = cancel_pending_order = close_position = create_pending_order


def test_capture_start_needs_no_broker_account_or_login(settings, tmp_path):
    from tests.dashboard.test_signal_copy import packet

    def forbidden(*args, **kwargs):
        raise AssertionError('Capture must not create a broker session')

    controller = DashboardController(settings.model_copy(update={'account_id': ''}), tmp_path, api_factory=forbidden)
    try:
        controller.receive_signals([packet()])
        assert controller.source_signal_feed() == []
        state = controller.start_capture()
        assert state['running'] and controller.api is None
        assert not controller.native.armed and not controller.signal_copy.armed
        event = packet(clientEventId='x17', detail='x17-spine bar=42')
        controller.receive_signals([event])
        controller.receive_signals([event])
        feed = controller.source_signal_feed()
        assert len(feed) == 1 and feed[0]['meaning']['source']['code'] == 'X17'
        assert feed[0]['price'] == 100
    finally:
        controller.close()


def test_capture_start_preserves_existing_broker_connection(settings, tmp_path):
    controller = DashboardController(settings, tmp_path)
    closed = []
    owner = SimpleNamespace(close=lambda: closed.append(True), connection=SimpleNamespace(session_expires_at=None))
    controller.api = owner
    controller.connection = 'connected'
    try:
        controller.start_capture()
        assert controller.api is owner and not closed
        assert controller.connection == 'connected'
    finally:
        controller.close()


def test_r01_csv_capture_without_broker_account(settings, tmp_path):
    import time
    ledger = tmp_path / 'r01.csv'
    ledger.write_text('utc,kind,label,symbol,side,entry,sl,tp\n')
    controller = DashboardController(settings.model_copy(update={'account_id': ''}), tmp_path / 'data', ledger_path=ledger)
    try:
        controller.start_capture()
        with ledger.open('a') as stream:
            stream.write('2026-09-11T12:00:00Z,intent,R01-one,XAUUSD,long,100,95,105\n')
        deadline = time.monotonic() + 3
        while not controller.source_signal_feed() and time.monotonic() < deadline:
            time.sleep(.05)
        row = controller.source_signal_feed()[0]
        assert row['meaning']['source']['code'] == 'R01'
        assert row['symbol'] == 'XAUUSD' and controller.api is None
    finally:
        controller.close()


def test_signals_are_captured_while_disarmed_and_never_reach_the_broker(settings, tmp_path):
    from tests.dashboard.test_signal_copy import config, packet
    controller = DashboardController(settings, tmp_path, api_factory=VerifiedAPI, interactive_copying=True)
    try:
        controller.connect('123')
        controller.configure_signals(config(destination_account='123'))
        controller.start('123')
        assert controller.status()['signal_copying'] is False
        result = controller.receive_signals([packet(), packet(clientEventId='cancel', kind='cancelled')])
        assert [r['status'] for r in result['results']] == ['held', 'captured']
        assert 'off' in result['results'][0]['reason']
        assert controller.api.writes == []
        assert controller.signal_copy.db.execute('SELECT count(*) FROM signals').fetchone()[0] == 2
        assert len(controller.source_signal_feed()) == 2
        assert controller.source_signal_feed()[0]['copy_result']['status'] == 'held'
    finally:
        controller.close()
    # A restart never re-arms: the switch lives in memory only.
    again = DashboardController(settings, tmp_path, api_factory=VerifiedAPI, interactive_copying=True)
    try:
        assert again.signal_copy.armed is False and again.status()['signal_copying'] is False
        assert again.signal_copy.config.destination_account == '123'
    finally:
        again.close()


def test_signal_arming_requires_connected_destination_and_stop_disarms(settings, tmp_path):
    from tests.dashboard.test_signal_copy import config
    controller = DashboardController(settings, tmp_path, api_factory=VerifiedAPI, interactive_copying=True)
    try:
        with pytest.raises(ValueError):
            controller.set_signal_copying(True)
        controller.connect('123')
        with pytest.raises(ValueError):
            controller.set_signal_copying(True)  # no settings yet
        controller.configure_signals(config(destination_account='123'))
        with pytest.raises(ValueError):
            controller.set_signal_copying('yes')
        assert controller.set_signal_copying(True)['live'] is True
        assert controller.status()['signal_copying'] is True
        with pytest.raises(ValueError, match='signal copying off'):
            controller.set_copying(True)
        with pytest.raises(ValueError):
            controller.configure_signals(config(destination_account='123'))
        controller.stop()
        assert controller.signal_copy.armed is False
        assert controller.status()['signal_copying'] is False
        # Reconnecting or selecting another account also drops the switch.
        controller.connect('123')
        controller.configure_signals(config(destination_account='123'))
        controller.set_signal_copying(True)
        controller.connect('123')
        assert controller.signal_copy.armed is False
    finally:
        controller.close()
