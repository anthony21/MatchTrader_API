"""Pending cancellation follows Live/Paper; lifecycle closes never close filled positions."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from matchtrader.capture.event import CaptureEvent
from matchtrader.dashboard.controller import DashboardController
from matchtrader.dashboard.server import Handler
from matchtrader.models.account import Account
from matchtrader.models.instrument import Instrument
from matchtrader.models.operation import Operation
from matchtrader.models.position import Position
from tests.dashboard.test_server import call
from tests.dashboard.test_server import server as server
from tests.dashboard.test_signal_copy import packet

LABEL = "0_264_0_273"


class UnwindAPI:
    """A connected, write-enabled owner session: serves the preflight read, the one send, the
    broker's own order/position view, and the cancel/close writes - counting every write."""

    def __init__(self, settings):
        self.settings = settings
        self.closed = False
        self.connection = SimpleNamespace(session_expires_at=None, account_id=settings.account_id)
        self.writes = []
        self.orders = []
        self.positions = []

    def login(self):
        return SimpleNamespace(tradingAccounts=[Account(tradingAccountId="123")])

    def close(self):
        self.closed = True

    def instruments(self):
        return [Instrument(symbol="EURUSD", volumeMin=".01", volumeMax="50", volumeStep=".01")]

    def active_orders(self):
        return self.orders

    def open_positions(self):
        return self.positions

    def create_pending_order(self, **kwargs):
        self.writes.append(("CREATE", kwargs))
        self.orders = [SimpleNamespace(id="aqua-1", symbol=kwargs["instrument"], side=kwargs["orderSide"],
                                       type=kwargs["type"])]
        return Operation(orderId="aqua-1")

    def open_position(self, **kwargs):
        self.writes.append(("MARKET", kwargs))
        self.positions = [Position(id="aqua-p1", symbol=kwargs["instrument"], side=kwargs["orderSide"],
                                   volume=kwargs["volume"], openPrice="1.15", openTimeMillis=1789000000000)]
        return Operation(orderId="aqua-m1", positionId="aqua-p1")

    def cancel_pending_order(self, **kwargs):
        self.writes.append(("CANCEL", kwargs))
        self.orders = []
        return Operation(status="OK")

    def close_position(self, **kwargs):
        self.writes.append(("CLOSE", kwargs))
        self.positions = []
        return Operation(status="OK")


class Forbidden:
    """A broker that fails the test on any access: the paper path must never reach it."""

    connection = SimpleNamespace(session_expires_at=None, account_id="123")

    def close(self):
        pass

    def __getattr__(self, name):
        raise AssertionError(f"A paper send must never reach the broker: {name}")


def labelled_event(label=LABEL, order_type="LIMIT", order_id="order-1", event_id="event-1"):
    """An X17 order as the capture extension reports it: the lifecycle label is the order comment."""
    return CaptureEvent(
        event_id=event_id, machine="qt", connection_id="connection", account_id="source", order_id=order_id,
        request_id="run:" + order_id, emitted_at=datetime.now(UTC), kind="ACCEPTED", action="CREATE",
        source="X17", source_label=label, symbol="EURUSD", side="BUY", order_type=order_type, quantity="1",
        price="1.15000", sl="1.14980", tp="1.16",
    )


def lifecycle(kind, event_id, label=LABEL, **changes):
    return packet(kind=kind, clientEventId=event_id, label=label, symbol="EURUSD", **changes)


@pytest.fixture
def controller(settings, tmp_path):
    value = DashboardController(settings, tmp_path, api_factory=UnwindAPI, interactive_copying=True)
    value.connect("123")
    value.start("123")
    yield value
    value.close()


def ledger_row(controller):
    (row,) = Handler.dashboard_sections(controller, [])["verified_trades"]["rows"]
    return row


@pytest.mark.parametrize("after", [
    {"mode": "live", "sources": {"X17": False}},   # the source switched off since the send
    {"mode": "paper", "sources": {"X17": True}},   # the master switch back on paper
    {"mode": "paper", "sources": {}},              # both
])
def test_cancel_signal_obeys_paper_live_without_a_second_source_gate(controller, after):
    api = controller.api
    trade_id = controller.receive_native(labelled_event().model_dump())["trade_id"]
    # An intent for this lifecycle arriving through the signal path opens nothing: sends are explicit.
    intent = controller.receive_signals([lifecycle("intent", "intent-1", detail="x17-spine bar=1")])["results"][0]
    assert intent["status"] == "held" and api.writes == []
    assert controller.native_store.trade(trade_id)["state"] == "observed"
    controller.configure_copy_controls({"mode": "live", "sources": {"X17": True}})
    sent = controller.send_trade({"trade_id": trade_id, "volume": "0.02"})
    assert sent["status"] == "accepted" and sent["broker_order_id"] == "aqua-1"
    controller.configure_copy_controls(after)
    assert controller.signal_copy.armed is False
    result = controller.receive_signals([lifecycle("cancelled", "cancel-1")])["results"][0]
    if after['mode'] == 'paper':
        assert result['status'] == 'captured'
        assert [name for name, _ in api.writes] == ['CREATE']
        return
    assert result["status"] == "accepted" and result["copy_request"]["id"] == "aqua-1"
    assert [name for name, _ in api.writes] == ["CREATE", "CANCEL"]
    assert controller.native_store.trade(trade_id)["state"] == "resolved"
    row = ledger_row(controller)
    assert row["state"] == "cancelled" and row["verified"] is False
    assert row["unwind"]["action"] == "CANCEL" and row["unwind"]["outcome"] == "accepted"
    assert row["unwind"]["origin"] == "broker" and "aqua-1" in row["unwind"]["summary"]
    assert row["cancellation"]["origin"] == "broker" and row["cancellation"]["outcome"] == "accepted"
    # The signal feed shows the same outcome for the cancel.
    feed = {r["id"]: r for r in controller.source_signal_feed()}
    assert feed["signal:qt:cancel-1"]["copy_result"]["status"] == "accepted"
    # A second cancel for the same lifecycle has nothing left to do; the broker is not asked again.
    again = controller.receive_signals([lifecycle("cancelled", "cancel-2")])["results"][0]
    assert again["status"] == "held" and "already resolved" in again["reason"]
    assert len(api.writes) == 2


def test_a_closed_signal_leaves_the_filled_position_alone(controller):
    api = controller.api
    trade_id = controller.receive_native(labelled_event(order_type="MARKET").model_dump())["trade_id"]
    controller.configure_copy_controls({"mode": "live", "sources": {"X17": True}})
    assert controller.send_trade({"trade_id": trade_id, "volume": "0.02"})["broker_position_id"] == "aqua-p1"
    controller.configure_copy_controls({"mode": "paper", "sources": {}})
    closed = lifecycle("closed", "closed-1", detail="res win=1")
    result = controller.receive_signals([closed])["results"][0]
    assert result['status'] == 'captured'
    assert [name for name, _ in api.writes] == ['MARKET']
    assert len(api.positions) == 1
    assert ledger_row(controller)['unwind'] is None
    again = controller.receive_signals([closed])['results'][0]
    assert again['duplicate'] and len(api.writes) == 1


def test_failure_after_an_unwind_write_is_not_reported_as_never_sent(controller, monkeypatch):
    from matchtrader.capture import unwind
    trade_id = controller.receive_native(labelled_event().model_dump())['trade_id']
    controller.configure_copy_controls({'mode': 'live', 'sources': {'X17': True}})
    controller.send_trade({'trade_id': trade_id, 'volume': '0.02'})
    original = unwind.apply
    def interrupted(*args):
        original(*args)
        raise RuntimeError('after completion')
    monkeypatch.setattr(unwind, 'apply', interrupted)
    result = controller.receive_signals([lifecycle('cancelled', 'interrupted')])['results'][0]
    assert result['status'] == 'uncertain'
    assert 'before any broker write' not in result['reason']
    assert [name for name, _ in controller.api.writes] == ['CREATE', 'CANCEL']


def test_a_paper_send_is_never_unwound_at_the_broker(controller):
    trade_id = controller.receive_native(labelled_event().model_dump())["trade_id"]
    controller.configure_copy_controls({"mode": "paper", "sources": {"X17": True}})
    assert controller.send_trade({"trade_id": trade_id, "volume": "0.02"})["mode"] == "paper"
    controller.api = Forbidden()
    try:
        for kind in ("cancelled", "closed"):
            result = controller.receive_signals([lifecycle(kind, "end-" + kind)])["results"][0]
            assert result["status"] == "captured"
        trade = controller.native_store.trade(trade_id)
        assert trade["state"] == "observed" and trade["broker_order_id"] == "" and trade["destination"] == ""
        row = ledger_row(controller)
        assert row["state"] == "paper_sent" and row["unwind"] is None
    finally:
        controller.api = None


def test_an_uncertain_unwind_is_never_retried_across_a_restart(settings, tmp_path):
    first = DashboardController(settings, tmp_path, api_factory=UnwindAPI, interactive_copying=True)
    first.connect("123")
    first.start("123")
    api = first.api
    try:
        trade_id = first.receive_native(labelled_event().model_dump())["trade_id"]
        first.configure_copy_controls({"mode": "live", "sources": {"X17": True}})
        first.send_trade({"trade_id": trade_id, "volume": "0.02"})

        def timeout(**kwargs):
            api.writes.append(("CANCEL", kwargs))
            raise TimeoutError()

        api.cancel_pending_order = timeout
        result = first.receive_signals([lifecycle("cancelled", "cancel-1")])["results"][0]
        assert result["status"] == "uncertain" and "TimeoutError" in result["reason"]
        assert first.native_store.trade(trade_id)["state"] == "uncertain"
        row = ledger_row(first)
        assert row["state"] == "uncertain" and row["unwind"]["outcome"] == "uncertain"
        assert row["cancellation"]["code"] == "TimeoutError" and row["cancellation"]["origin"]
    finally:
        first.close()
    second = DashboardController(settings, tmp_path, api_factory=UnwindAPI, interactive_copying=True)
    second.connect("123")
    second.start("123")
    try:
        for event_id in ("cancel-1", "cancel-2"):
            again = second.receive_signals([lifecycle("cancelled", event_id)])["results"][0]
            assert again["status"] == ('held' if event_id == 'cancel-1' else 'captured')
        assert [name for name, _ in second.api.writes] == []
        assert second.native_store.trade(trade_id)["state"] == "uncertain"
    finally:
        second.close()


def test_a_cancel_signal_over_the_wire_cancels_the_sent_order_without_any_click(server):
    """The relay's own path: POST /capture/signals with the bridge token. The owner sent the trade
    live from the Verified trades page, left the master in Live with source controls off, and X17 then
    reported the lifecycle cancelled: the resting order is cancelled at once, exactly once."""
    controller = server.controller
    controller.settings = controller.settings.model_copy(update={"enable_writes": True})
    broker = UnwindAPI(controller.settings)
    controller.api = broker
    controller.connection = "connected"
    session = {"X-Session-Token": "test-session"}
    sender = {"Authorization": "Bearer " + server.bridge_token}
    assert call(server, "/api/start", "POST", {"account_id": "123"}, session)[0] == 200
    try:
        status, body = call(server, "/capture/events", "POST", labelled_event().model_dump(mode="json"), sender)
        trade_id = json.loads(body)["trade_id"]
        assert status == 202 and json.loads(body)["status"] == "held"
        call(server, "/api/copy-controls", "POST", {"mode": "live", "sources": {"X17": True}}, session)
        status, body = call(server, "/api/trades/send", "POST", {"trade_id": trade_id, "volume": "0.02"}, session)
        assert status == 200 and json.loads(body)["broker_order_id"] == "aqua-1"
        call(server, "/api/copy-controls", "POST", {"mode": "live", "sources": {}}, session)
        cancel = lifecycle("cancelled", "cancel-1")
        # A browser can never deliver a signal; only the authenticated relay can.
        assert call(server, "/capture/signals", "POST", [cancel], {**sender, "Origin": "http://127.0.0.1:8765"})[0] == 401
        assert call(server, "/capture/signals", "POST", [cancel], session)[0] == 401
        status, body = call(server, "/capture/signals", "POST", [cancel], sender)
        result = json.loads(body)["results"][0]
        assert status == 202 and result["status"] == "accepted" and result["copy_request"]["id"] == "aqua-1"
        assert [name for name, _ in broker.writes] == ["CREATE", "CANCEL"]
        row = ledger_row(controller)
        assert row["state"] == "cancelled" and row["unwind"]["outcome"] == "accepted"
        status, body = call(server, "/capture/signals", "POST", [cancel], sender)
        assert status == 202 and json.loads(body)["results"][0]["duplicate"] and len(broker.writes) == 2
    finally:
        controller.api = None
