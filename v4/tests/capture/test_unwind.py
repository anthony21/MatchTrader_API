"""unwind: a cancel/closed signal removes exposure the owner created, at once, exactly once, and never opens."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from matchtrader.capture import CaptureStore, unwind
from matchtrader.capture.manual_send import send
from matchtrader.capture.router import CaptureRouter
from matchtrader.core.errors import APIError, WritesDisabledError
from matchtrader.core.reason import broker_reason
from matchtrader.dashboard.copy_controls import CopyControls
from matchtrader.dashboard.signal_copy import Signal
from matchtrader.models.instrument import Instrument
from matchtrader.models.operation import Operation
from matchtrader.models.position import Position

LABEL = "0_264_0_273"


class NeverCalled:
    """A broker that fails the test on any attribute access."""

    def __getattr__(self, name):
        raise AssertionError(f"Unwind reached the broker without a sent trade: {name}")


class Broker:
    """Serves the preflight read, the one create, and the broker's own view of orders/positions."""

    connection = SimpleNamespace(session_expires_at=None, account_id="demo")

    def __init__(self):
        self.calls = []
        self.orders = []
        self.positions = []

    def instruments(self):
        return [Instrument(symbol="EURUSD", volumeMin=".01", volumeMax="50", volumeStep=".01")]

    def active_orders(self):
        return self.orders

    def open_positions(self):
        return self.positions

    def create_pending_order(self, **kwargs):
        self.calls.append(("CREATE", kwargs))
        self.orders = [SimpleNamespace(id="aqua1", symbol=kwargs["instrument"], side=kwargs["orderSide"],
                                       type=kwargs["type"])]
        return Operation(orderId="aqua1")

    def open_position(self, **kwargs):
        self.calls.append(("MARKET", kwargs))
        self.positions = [Position(id="position1", symbol=kwargs["instrument"], side=kwargs["orderSide"],
                                   volume=kwargs["volume"], openPrice="1.15", openTimeMillis=1789000000000)]
        return Operation(orderId="market1", positionId="position1")

    def cancel_pending_order(self, **kwargs):
        self.calls.append(("CANCEL", kwargs))
        self.orders = [o for o in self.orders if o.id != kwargs["id"]]
        return Operation(status="OK")

    def close_position(self, **kwargs):
        self.calls.append(("CLOSE", kwargs))
        self.positions = [p for p in self.positions if p.id != kwargs["positionId"]]
        return Operation(status="OK")

    def writes(self):
        return [name for name, _ in self.calls if name != "CREATE" and name != "MARKET"]


def signal(kind="cancelled", event_id="c1", label=LABEL, symbol="EURUSD", machine="qt"):
    return Signal.model_validate({
        "clientEventId": event_id, "machineId": machine, "source": "chain", "kind": kind, "label": label,
        "timestampUtc": datetime.now(UTC).isoformat(), "symbol": symbol, "side": "long",
    })


def captured(tmp_path, event, **changes):
    """One ACCEPTED CREATE labelled by the strategy, held by the disarmed router: a candidate."""
    store = CaptureStore(tmp_path)
    labelled = event.model_copy(update={"source": "X17", "source_label": LABEL, **changes})
    result = CaptureRouter(store).receive(labelled.model_dump())
    assert result["status"] == "held" and result["broker_order_id"] == ""
    return store, result["trade_id"]


def sent(tmp_path, event, broker, **changes):
    """The owner's explicit live send, through manual_send; the only way anything opens."""
    store, trade_id = captured(tmp_path, event, **changes)
    result = send(store, CopyControls.model_validate({"mode": "live", "sources": {"X17": True}}),
                  trade_id, "0.02", broker, "demo")
    assert result["status"] == "accepted"
    return store, trade_id


def rows(store, table, trade_id):
    return [dict(r) for r in store.db.execute(f"SELECT * FROM {table} WHERE trade_id=?", (trade_id,))]


def test_cancel_signal_cancels_the_live_pending_order_exactly_once(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)
    assert store.trade(trade_id)["state"] == "pending"
    outcome = unwind.apply(store, signal(), broker, "demo", True)
    assert outcome["decision"] == "accepted" and outcome["trade_id"] == trade_id
    assert broker.writes() == ["CANCEL"]
    assert broker.calls[-1][1] == {"instrument": "EURUSD", "id": "aqua1", "orderSide": "BUY", "type": "LIMIT"}
    trade = store.trade(trade_id)
    assert trade["state"] == "resolved" and trade["resolved_at"] and trade["last_request"] == "c1"
    (attempt,) = [a for a in rows(store, "attempts", trade_id) if a["action_key"] != "CREATE"]
    assert (attempt["action_key"], attempt["state"]) == ("CANCEL:signal:c1", "accepted")
    (history,) = [h for h in rows(store, "action_history", trade_id) if h["action"] == "CANCEL"]
    assert history["outcome"] == "accepted" and history["request_id"] == "c1"
    assert json.loads(history["request"])["id"] == "aqua1"
    (reason,) = [r for r in rows(store, "outcome_reasons", trade_id) if r["action_key"] == "CANCEL:signal:c1"]
    assert (reason["origin"], reason["outcome"], reason["code"]) == ("broker", "accepted", "OK")
    assert "aqua1" in reason["summary"] and LABEL in reason["summary"] and "c1" in reason["evidence"]
    # A later, different cancel for the same lifecycle finds nothing left to do and says so.
    again = unwind.apply(store, signal(event_id="c2"), broker, "demo", True)
    assert again["decision"] == "held" and "already resolved" in again["reason"]
    assert broker.writes() == ["CANCEL"]
    store.close()


def test_closed_signal_closes_the_open_position_exactly_once(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker, order_type="MARKET")
    assert store.trade(trade_id)["broker_position_id"] == "position1"
    outcome = unwind.apply(store, signal("closed", "x1"), broker, "demo", True)
    assert outcome["decision"] == "accepted"
    assert broker.writes() == ["CLOSE"]
    assert broker.calls[-1][1] == {"instrument": "EURUSD", "orderSide": "BUY", "positionId": "position1",
                                   "volume": Decimal("0.02")}
    assert store.trade(trade_id)["state"] == "resolved"
    # The broker's own position read taken before closing is kept as read-back evidence.
    (observed,) = rows(store, "destination_observations", trade_id)
    assert observed["position_id"] == "position1" and observed["reader"] == "open_positions"
    (reason,) = [r for r in rows(store, "outcome_reasons", trade_id) if r["action_key"] == "CLOSE:signal:x1"]
    assert reason["origin"] == "broker" and "position1" in reason["summary"]
    again = unwind.apply(store, signal("closed", "x2"), broker, "demo", True)
    assert again["decision"] == "held" and broker.writes() == ["CLOSE"]
    store.close()


def test_closed_signal_learns_the_position_id_from_the_opening_order_before_closing(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)  # a LIMIT: only the order id is known
    # The order filled at the broker since; reconcile has not run yet.
    broker.orders = []
    broker.positions = [Position(id="filled-p", symbol="EURUSD", side="BUY", volume="0.02", openPrice="1.15",
                                 openTimeMillis=1789000000000, orderId="aqua1")]
    outcome = unwind.apply(store, signal("closed", "x1"), broker, "demo", True)
    assert outcome["decision"] == "accepted" and broker.writes() == ["CLOSE"]
    assert broker.calls[-1][1]["positionId"] == "filled-p"
    assert store.trade(trade_id)["broker_position_id"] == "filled-p"
    store.close()


def test_newly_discovered_merged_position_is_not_closed(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)
    other = event.model_copy(update={'event_id': 'other-event', 'order_id': 'other-order',
                                     'source_label': 'different-lifecycle'})
    other_id = CaptureRouter(store).receive(other.model_dump())['trade_id']
    broker.orders = []
    broker.positions = [Position(id='merged', symbol='EURUSD', side='BUY', volume='.04',
                                 openPrice='1.15', orderId='aqua1')]
    store.observe_positions(other_id, 'demo', broker.positions)
    result = unwind.apply(store, signal('closed'), broker, 'demo', True)
    assert result['decision'] == 'held' and 'Merged' in result['reason']
    assert broker.writes() == []
    assert rows(store, 'attempts', trade_id)[0]['action_key'] == 'CREATE'
    store.close()


def test_preflight_read_failure_is_recorded_without_claiming_a_write(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)
    def unavailable():
        raise APIError('HTTP 503', 503, reason=broker_reason(503, {'status': 'ERROR'}))
    broker.active_orders = unavailable
    result = unwind.apply(store, signal(), broker, 'demo', True)
    assert result['decision'] == 'held' and 'no broker write' in result['reason']
    assert broker.writes() == [] and store.trade(trade_id)['state'] == 'pending'
    reason = rows(store, 'outcome_reasons', trade_id)[-1]
    assert reason['origin'] == 'broker' and reason['outcome'] == 'held'
    store.close()


def test_connected_account_must_match_destination(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)
    broker.connection = SimpleNamespace(account_id='other-account')
    result = unwind.apply(store, signal(), broker, 'demo', True)
    assert result['decision'] == 'held' and 'different account' in result['reason']
    assert broker.writes() == [] and store.trade(trade_id)['state'] == 'pending'
    store.close()


def test_closed_signal_for_a_copy_that_never_filled_cancels_the_resting_order(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)
    outcome = unwind.apply(store, signal("closed", "x1"), broker, "demo", True)
    assert outcome["decision"] == "accepted" and broker.writes() == ["CANCEL"]
    assert "resting order" in outcome["reason"] and store.trade(trade_id)["state"] == "resolved"
    store.close()


def test_paper_sent_trade_is_a_no_op_and_never_touches_the_broker(tmp_path, event):
    store, trade_id = captured(tmp_path, event)
    send(store, CopyControls.model_validate({"mode": "paper", "sources": {"X17": True}}), trade_id, "0.02",
         NeverCalled(), "demo")
    before = store.trade(trade_id)
    for kind in ("cancelled", "cancel", "closed"):
        outcome = unwind.apply(store, signal(kind, "p-" + kind), NeverCalled(), "demo", True)
        assert outcome["decision"] == "held" and "paper mode only" in outcome["reason"]
    assert store.trade(trade_id) == before
    assert [a["action_key"] for a in rows(store, "attempts", trade_id)] == []
    reasons = rows(store, "outcome_reasons", trade_id)
    assert len(reasons) == 3 and {r["code"] for r in reasons} == {"LifecycleEndedBeforeSend"}
    assert all(r["origin"] == "local" and r["evidence"] for r in reasons)
    store.close()


def test_a_trade_with_no_broker_id_is_a_no_op(tmp_path, event):
    store, trade_id = captured(tmp_path, event)  # never sent in any mode
    outcome = unwind.apply(store, signal(), NeverCalled(), "demo", True)
    assert outcome["decision"] == "held" and "never sent live" in outcome["reason"]
    assert store.trade(trade_id)["state"] == "observed" and rows(store, "attempts", trade_id) == []
    # A live send that landed uncertain also has no confirmed id: reconcile, never act.
    broker = Broker()

    def timeout(**kwargs):
        raise TimeoutError()

    broker.create_pending_order = timeout
    store2, trade2 = captured(tmp_path / "two", event)
    send(store2, CopyControls.model_validate({"mode": "live", "sources": {"X17": True}}), trade2, "0.02",
         broker, "demo")
    assert store2.trade(trade2)["state"] == "uncertain"
    outcome = unwind.apply(store2, signal(), NeverCalled(), "demo", True)
    assert outcome["decision"] == "held" and "never sent live" in outcome["reason"]
    store.close()
    store2.close()


def test_no_linked_trade_is_none_and_a_shared_label_is_ambiguous(tmp_path, event):
    broker = Broker()
    store, first = sent(tmp_path, event, broker)
    assert unwind.apply(store, signal(label="other"), NeverCalled(), "demo", True) is None
    assert unwind.apply(store, signal(machine="elsewhere"), NeverCalled(), "demo", True) is None
    second_event = event.model_copy(update={"event_id": "event2", "order_id": "order2", "source": "X17",
                                            "source_label": LABEL})
    second = CaptureRouter(store).receive(second_event.model_dump())["trade_id"]
    outcome = unwind.apply(store, signal(), NeverCalled(), "demo", True)
    assert outcome["decision"] == "held" and "2 sent trades share" in outcome["reason"]
    assert first in outcome["reason"] and second in outcome["reason"]
    assert store.trade(first)["state"] == "pending" and broker.writes() == []
    store.close()


def test_uncertain_outcome_is_recorded_and_never_retried(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)

    def timeout(**kwargs):
        broker.calls.append(("CANCEL", kwargs))
        raise TimeoutError()

    broker.cancel_pending_order = timeout
    outcome = unwind.apply(store, signal(), broker, "demo", True)
    assert outcome["decision"] == "uncertain" and "reconciliation" in outcome["reason"]
    assert "TimeoutError" in outcome["reason"] and trade_id in outcome["reason"]
    trade = store.trade(trade_id)
    assert trade["state"] == "uncertain"
    (attempt,) = [a for a in rows(store, "attempts", trade_id) if a["action_key"] != "CREATE"]
    assert attempt["state"] == "uncertain"
    (reason,) = [r for r in rows(store, "outcome_reasons", trade_id) if r["action_key"] == "CANCEL:signal:c1"]
    assert reason["outcome"] == "uncertain" and reason["code"] == "TimeoutError"
    assert reason["origin"] and reason["evidence"] and "unknown" not in reason["code"].lower()
    # The same signal again, and a fresh one for the same lifecycle, both stop before the wire.
    for event_id in ("c1", "c2"):
        again = unwind.apply(store, signal(event_id=event_id), broker, "demo", True)
        assert again["decision"] == "held" and "uncertain" in again["reason"]
    assert broker.writes() == ["CANCEL"]
    store.close()


def test_broker_refusal_is_recorded_with_broker_origin_and_its_code(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)

    def refused(**kwargs):
        raise APIError("HTTP 400 from Match-Trader", 400,
                       reason=broker_reason(400, {"status": "ERROR", "errorMessage": "Order not found",
                                                  "nativeCode": "ORDER_NOT_FOUND"}))

    broker.cancel_pending_order = refused
    outcome = unwind.apply(store, signal(), broker, "demo", True)
    assert outcome["decision"] == "uncertain"
    (reason,) = [r for r in rows(store, "outcome_reasons", trade_id) if r["action_key"] == "CANCEL:signal:c1"]
    assert (reason["origin"], reason["code"]) == ("broker", "ORDER_NOT_FOUND")
    assert reason["summary"] == "Order not found"
    store.close()


def test_merged_or_split_position_is_not_closed_and_says_why(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker, order_type="MARKET")
    with store.lock, store.db:
        store.mappings.link(trade_id, "destination", store.mappings.destination_scope("demo"), "position",
                            "position-extra", "test split", "2026-09-11T00:00:00+00:00")
    outcome = unwind.apply(store, signal("closed", "x1"), broker, "demo", True)
    assert outcome["decision"] == "held" and "Split destination positions" in outcome["reason"]
    assert broker.writes() == [] and store.trade(trade_id)["state"] == "open"
    (reason,) = [r for r in rows(store, "outcome_reasons", trade_id) if r["action_key"] == "CLOSE:signal:x1"]
    assert reason["code"] == "PositionGuard" and reason["origin"] == "local"
    # A merge: another trade owns the same destination position.
    other = CaptureRouter(store).receive(event.model_copy(update={
        "event_id": "event2", "order_id": "order2", "source": "X17", "source_label": "other"}).model_dump())
    with store.lock, store.db:
        store.db.execute("DELETE FROM identity_links WHERE native_id='position-extra'")
        store.mappings.link(other["trade_id"], "destination", store.mappings.destination_scope("demo"), "position",
                            "position1", "test merge", "2026-09-11T00:00:00+00:00")
    outcome = unwind.apply(store, signal("closed", "x2"), broker, "demo", True)
    assert outcome["decision"] == "held" and "Merged destination position" in outcome["reason"]
    assert broker.writes() == []
    store.close()


def test_cancel_never_closes_a_filled_position_and_a_mismatched_order_is_refused(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)
    broker.orders = []  # filled since
    outcome = unwind.apply(store, signal(), broker, "demo", True)
    assert outcome["decision"] == "held" and "no longer pending" in outcome["reason"]
    assert "aqua1" in outcome["reason"] and broker.writes() == []
    broker.orders = [SimpleNamespace(id="aqua1", symbol="EURUSD", side="SELL", type="LIMIT")]
    outcome = unwind.apply(store, signal(event_id="c2"), broker, "demo", True)
    assert outcome["decision"] == "held" and "does not match" in outcome["reason"]
    assert broker.writes() == [] and store.trade(trade_id)["state"] == "pending"
    # A cancel for a market copy has nothing pending to cancel and never closes the position.
    store2, trade2 = sent(tmp_path / "market", event, Broker(), order_type="MARKET")
    outcome = unwind.apply(store2, signal(), Broker(), "demo", True)
    assert outcome["decision"] == "held" and "no position is closed" in outcome["reason"]
    assert "market1" in outcome["reason"] and store2.trade(trade2)["state"] == "open"
    store.close()
    store2.close()


def test_symbol_disagreement_on_a_matching_label_holds(tmp_path, event):
    broker = Broker()
    store, _ = sent(tmp_path, event, broker)
    outcome = unwind.apply(store, signal(symbol="US TECH 100"), broker, "demo", True)
    assert outcome["decision"] == "held" and "US TECH 100" in outcome["reason"] and "EURUSD" in outcome["reason"]
    assert broker.writes() == []
    # A signal without a symbol relies on the label alone.
    assert unwind.apply(store, signal(event_id="c2", symbol=""), broker, "demo", True)["decision"] == "accepted"
    store.close()


def test_disconnected_or_write_disabled_sessions_hold_with_an_investigable_reason(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)
    outcome = unwind.apply(store, signal(), None, "demo", False)
    assert outcome["decision"] == "held" and "not connected" in outcome["reason"] and "aqua1" in outcome["reason"]
    outcome = unwind.apply(store, signal(event_id="c2"), broker, "demo", False)
    assert outcome["decision"] == "held" and "not connected" in outcome["reason"]
    broker.settings = SimpleNamespace(enable_writes=False)
    outcome = unwind.apply(store, signal(event_id="c3"), broker, "demo", True)
    assert outcome["decision"] == "held" and "MTR_ENABLE_WRITES" in outcome["reason"]
    assert store.trade(trade_id)["state"] == "pending" and broker.writes() == []
    assert [a["action_key"] for a in rows(store, "attempts", trade_id)] == ["CREATE"]
    # The client refusing after the claim is still a known non-send: the trade is released.
    del broker.settings

    def disabled(**kwargs):
        raise WritesDisabledError("Set MTR_ENABLE_WRITES=true to use mutation endpoints")

    broker.cancel_pending_order = disabled
    outcome = unwind.apply(store, signal(event_id="c4"), broker, "demo", True)
    assert outcome["decision"] == "held" and "MTR_ENABLE_WRITES" in outcome["reason"]
    trade = store.trade(trade_id)
    assert trade["state"] == "pending"
    (attempt,) = [a for a in rows(store, "attempts", trade_id) if a["action_key"] == "CANCEL:signal:c4"]
    assert attempt["state"] == "held"
    # Once writes are back a new cancel still acts, exactly once.
    broker.cancel_pending_order = Broker.cancel_pending_order.__get__(broker)
    assert unwind.apply(store, signal(event_id="c5"), broker, "demo", True)["decision"] == "accepted"
    assert broker.writes() == ["CANCEL"]
    store.close()


def test_other_destination_holds(tmp_path, event):
    broker = Broker()
    store, _ = sent(tmp_path, event, broker)
    outcome = unwind.apply(store, signal(), broker, "other-account", True)
    assert outcome["decision"] == "held" and "'demo'" in outcome["reason"] and "'other-account'" in outcome["reason"]
    assert broker.writes() == []
    store.close()


def test_unrecognized_completion_status_lands_uncertain_with_local_origin(tmp_path, event):
    broker = Broker()
    store, trade_id = sent(tmp_path, event, broker)
    broker.cancel_pending_order = lambda **kwargs: Operation(status="PENDING")
    outcome = unwind.apply(store, signal(), broker, "demo", True)
    assert outcome["decision"] == "uncertain" and outcome["response"] == {
        "status": "PENDING", "nativeCode": None, "errorMessage": None, "orderId": None, "positionId": None}
    (reason,) = [r for r in rows(store, "outcome_reasons", trade_id) if r["action_key"] == "CANCEL:signal:c1"]
    assert reason["origin"] == "local" and "completion status" in reason["summary"]
    store.close()


def test_pending_order_request_is_the_shared_check(tmp_path):
    api = SimpleNamespace(active_orders=lambda: [SimpleNamespace(id="o1", symbol="NAS100", side="SELL", type="STOP")])
    request = {"instrument": "NAS100", "orderSide": "SELL", "type": "STOP"}
    assert unwind.pending_order_request(api, "o1", request) == {
        "instrument": "NAS100", "id": "o1", "orderSide": "SELL", "type": "STOP"}
    with pytest.raises(ValueError, match="no longer pending"):
        unwind.pending_order_request(api, "o2", request)
    with pytest.raises(ValueError, match="does not match"):
        unwind.pending_order_request(api, "o1", {**request, "type": "LIMIT"})
