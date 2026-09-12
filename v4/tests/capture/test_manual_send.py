"""manual_send: a captured signal is only a candidate; nothing reaches the broker without a send."""

import json
from decimal import Decimal

import pytest

from matchtrader.capture import CaptureStore
from matchtrader.capture.manual_send import ALREADY_SENT, PAPER_VERDICT, parse_volume, send
from matchtrader.capture.reconcile import reconcile
from matchtrader.capture.router import CaptureRouter
from matchtrader.capture.verified import classify
from matchtrader.dashboard.copy_controls import CopyControls
from matchtrader.models.position import Position


class NeverCalled:
    """A broker that fails the test on any attribute access: the paper path must never touch it."""

    def __getattr__(self, name):
        raise AssertionError(f"Paper mode reached the broker: {name}")


def controls(mode="paper", **sources):
    return CopyControls.model_validate({"mode": mode, "sources": sources})


def captured(tmp_path, event, route=None):
    """Record one ACCEPTED CREATE through the disarmed router: captured and held, never sent."""
    store = CaptureStore(tmp_path)
    result = CaptureRouter(store, route).receive(event.model_dump())
    assert result["status"] == "held" and result["broker_order_id"] == ""
    return store, result["trade_id"]


def rows(store, table, trade_id):
    return store.db.execute(f"SELECT * FROM {table} WHERE trade_id=?", (trade_id,)).fetchall()


def test_capture_alone_never_dispatches_and_the_defaults_refuse_every_source(tmp_path, event):
    store, trade_id = captured(tmp_path, event)
    assert store.trade(trade_id)["state"] == "observed"
    with pytest.raises(ValueError, match="MANUAL is not enabled"):
        send(store, CopyControls(), trade_id, "0.25", NeverCalled(), "demo")
    assert rows(store, "paper_sends", trade_id) == [] and rows(store, "attempts", trade_id) == []
    store.close()


def test_enabling_other_sources_does_not_make_this_one_eligible(tmp_path, event):
    store, trade_id = captured(tmp_path, event)  # the fixture event is attributed to MANUAL
    with pytest.raises(ValueError, match="MANUAL is not enabled"):
        send(store, controls("live", P01=True, X17=True), trade_id, "0.25", NeverCalled(), "demo")
    assert rows(store, "attempts", trade_id) == []
    store.close()


def test_paper_send_records_the_exact_request_and_never_touches_the_broker(tmp_path, event):
    store, trade_id = captured(tmp_path, event)
    result = send(store, controls(MANUAL=True), trade_id, "0.25", NeverCalled(), "demo")
    assert result["mode"] == "paper" and result["status"] == "paper" and result["verdict"] == PAPER_VERDICT
    assert result["broker_order_id"] == "" and result["broker_position_id"] == ""
    request = result["request"]
    assert request["instrument"] == "EURUSD" and request["orderSide"] == "BUY" and request["type"] == "LIMIT"
    assert request["volume"] == "0.25"  # the text the owner typed, not a float
    assert Decimal(request["price"]) == event.price and Decimal(request["slPrice"]) == event.sl
    assert Decimal(request["tpPrice"]) == event.tp
    (row,) = rows(store, "paper_sends", trade_id)
    assert row["lots"] == "0.25" and row["destination"] == "demo" and row["source"] == "MANUAL"
    assert json.loads(row["request"]) == request and row["decided_at"] == result["decided_at"]
    trade = store.trade(trade_id)
    assert trade["state"] == "observed" and trade["destination"] == "" and trade["lots"] == ""
    assert trade["broker_order_id"] == "" and trade["broker_position_id"] == ""
    assert rows(store, "attempts", trade_id) == [] and rows(store, "action_history", trade_id) == []
    store.close()


def test_paper_send_is_structurally_incapable_of_verification(tmp_path, event, broker):
    store, trade_id = captured(tmp_path, event)
    send(store, controls(MANUAL=True), trade_id, "0.25", NeverCalled(), "demo")
    # Even with a matching position visible at the broker, the read-back pass has nothing to
    # attach it to: the paper trade owns no destination identity and is still 'observed'.
    broker.positions = [Position(id="aqua-p1", symbol="EURUSD", side="BUY", volume="0.25", openPrice="1.15",
                                 openTimeMillis=1789000000000)]
    reconcile(store, broker, "demo", broker.positions)
    assert store.db.execute("SELECT COUNT(*) FROM destination_observations").fetchone()[0] == 0
    (snapshot,) = store.mapping_view("demo")
    assert not any(link["side"] == "destination" for link in snapshot["links"])
    verdict = classify(snapshot)
    assert verdict["state"] == "candidate" and verdict["verified"] is False and verdict["read_back"] is None
    store.close()


def test_a_trade_is_sent_at_most_once_in_either_mode(tmp_path, event):
    store, trade_id = captured(tmp_path, event)
    send(store, controls(MANUAL=True), trade_id, "0.25", NeverCalled(), "demo")
    for mode in ("paper", "live"):
        with pytest.raises(ValueError, match=ALREADY_SENT):
            send(store, controls(mode, MANUAL=True), trade_id, "0.25", NeverCalled(), "demo")
    assert len(rows(store, "paper_sends", trade_id)) == 1 and rows(store, "attempts", trade_id) == []
    store.close()


@pytest.mark.parametrize("volume, lots", [
    ("0.25", "0.25"), ("0.1", "0.1"), (0.1, "0.1"), ("1", "1"), (2, "2"),
    (Decimal("0.07"), "0.07"), ("0.010", "0.010"), (" 0.5 ", "0.5"),
])
def test_volume_text_parses_losslessly(volume, lots):
    parsed = parse_volume(volume)
    assert isinstance(parsed, Decimal) and str(parsed) == lots


@pytest.mark.parametrize("volume", [
    None, True, False, "", "abc", "0", "-0.01", "NaN", "Infinity", "-Infinity", [], {}, "0x10",
])
def test_non_positive_or_non_numeric_volume_is_refused(volume):
    with pytest.raises(ValueError):
        parse_volume(volume)


def test_live_refuses_an_invalid_lot_step_before_any_write(tmp_path, event, broker):
    store, trade_id = captured(tmp_path, event)
    live = controls("live", MANUAL=True)
    with pytest.raises(ValueError, match="lot limits/step"):
        send(store, live, trade_id, "0.015", broker, "demo")  # instrument step is .01
    with pytest.raises(ValueError, match="lot limits/step"):
        send(store, live, trade_id, "0.005", broker, "demo")  # below volumeMin
    assert broker.calls == [] and rows(store, "attempts", trade_id) == []
    assert store.trade(trade_id)["state"] == "observed"
    # The refusal consumed nothing: a corrected volume still goes, exactly once.
    result = send(store, live, trade_id, "0.02", broker, "demo")
    assert result["status"] == "accepted" and broker.calls[0][1]["volume"] == Decimal("0.02")
    store.close()


def test_live_commits_the_attempt_sends_once_and_refuses_a_second_send(tmp_path, event, broker):
    store, trade_id = captured(tmp_path, event)
    live = controls("live", MANUAL=True)
    result = send(store, live, trade_id, "0.02", broker, "demo")
    assert result["mode"] == "live" and result["status"] == "accepted" and result["broker_order_id"] == "aqua1"
    assert broker.calls == [("CREATE", {"instrument": "EURUSD", "orderSide": "BUY", "volume": Decimal("0.02"),
                                        "slPrice": event.sl, "tpPrice": event.tp, "type": "LIMIT",
                                        "price": event.price})]
    trade = store.trade(trade_id)
    assert trade["state"] == "pending" and trade["lots"] == "0.02" and trade["destination"] == "demo"
    (attempt,) = rows(store, "attempts", trade_id)
    assert (attempt["action_key"], attempt["state"]) == ("CREATE", "accepted")
    (history,) = rows(store, "action_history", trade_id)
    assert history["outcome"] == "accepted" and json.loads(history["request"])["volume"] == "0.02"
    with pytest.raises(ValueError, match="not a candidate"):
        send(store, live, trade_id, "0.02", broker, "demo")
    assert len(broker.calls) == 1
    store.close()


def test_live_market_order_uses_open_position_and_is_accepted_not_verified(tmp_path, event, broker):
    store, trade_id = captured(tmp_path, event.model_copy(update={"order_type": "MARKET"}))
    result = send(store, controls("live", MANUAL=True), trade_id, "0.02", broker, "demo")
    assert result["status"] == "accepted" and result["broker_position_id"] == "position1"
    assert broker.calls[0][0] == "MARKET" and "type" not in broker.calls[0][1]
    assert store.trade(trade_id)["state"] == "open"
    # A write response is never read-back evidence.
    assert classify(store.mapping_view("demo")[0])["state"] == "sent_unconfirmed"
    store.close()


def test_live_broker_failure_lands_uncertain_with_an_investigable_reason_and_no_retry(tmp_path, event, broker):
    store, trade_id = captured(tmp_path, event)

    def timeout(**kwargs):
        broker.calls.append(("CREATE", kwargs))
        raise TimeoutError()

    broker.create_pending_order = timeout
    live = controls("live", MANUAL=True)
    result = send(store, live, trade_id, "0.02", broker, "demo")
    assert result["status"] == "uncertain" and "reconciliation" in result["reason"]
    assert store.trade(trade_id)["state"] == "uncertain"
    (reason,) = rows(store, "outcome_reasons", trade_id)
    assert reason["outcome"] == "uncertain" and reason["code"] == "TimeoutError"
    assert reason["origin"] and reason["evidence"] and "unknown" not in reason["code"].lower()
    with pytest.raises(ValueError, match="not a candidate"):
        send(store, live, trade_id, "0.02", broker, "demo")
    assert len(broker.calls) == 1
    store.close()


def test_live_without_a_connected_destination_is_refused(tmp_path, event):
    store, trade_id = captured(tmp_path, event)
    with pytest.raises(ValueError, match="Connect the destination"):
        send(store, controls("live", MANUAL=True), trade_id, "0.02", None, "demo")
    assert rows(store, "attempts", trade_id) == []
    store.close()


def test_preflight_read_failure_is_named_by_class_and_writes_nothing(tmp_path, event, broker):
    store, trade_id = captured(tmp_path, event)

    def unavailable():
        raise OSError("upstream detail that must not leak")

    broker.instruments = unavailable
    with pytest.raises(ValueError, match="OSError") as info:
        send(store, controls("live", MANUAL=True), trade_id, "0.02", broker, "demo")
    assert "upstream detail" not in str(info.value)
    assert broker.calls == [] and rows(store, "attempts", trade_id) == []
    assert store.trade(trade_id)["state"] == "observed"
    store.close()


def test_only_the_volume_is_editable_everything_else_comes_from_the_signal(tmp_path, event, route):
    # The route's symbol spelling is the one mapping consulted; its multiplier and cap are not.
    route.symbols = {"EUR/USD": route.symbols["EURUSD"]}
    store, trade_id = captured(tmp_path, event.model_copy(update={"symbol": "EUR/USD"}), route)
    result = send(store, controls(MANUAL=True), trade_id, "0.25", NeverCalled(), "demo", route=route)
    request = result["request"]
    assert request["instrument"] == "EURUSD" and request["orderSide"] == "BUY" and request["type"] == "LIMIT"
    assert Decimal(request["volume"]) == Decimal("0.25")  # not quantity * .01, not capped at .1
    assert Decimal(request["price"]) == event.price and Decimal(request["slPrice"]) == event.sl
    store.close()


@pytest.mark.parametrize("change, message", [
    ({"order_type": "STOP_LIMIT"}, "Unsupported order type"),
    ({"brackets_absolute": False}, "Offset brackets"),
    ({"side": ""}, "Missing side"),
])
def test_signal_shapes_the_router_refuses_are_refused_here_too(tmp_path, event, change, message):
    store, trade_id = captured(tmp_path, event.model_copy(update=change))
    with pytest.raises(ValueError, match=message):
        send(store, controls(MANUAL=True), trade_id, "0.25", NeverCalled(), "demo")
    assert rows(store, "paper_sends", trade_id) == []
    store.close()


def test_a_trade_whose_source_order_ended_is_no_longer_a_candidate(tmp_path, event):
    store, trade_id = captured(tmp_path, event)
    store.record(event.model_copy(update={"event_id": "ended", "kind": "ORDER", "status": "Cancelled"}))
    assert store.trade(trade_id)["state"] == "resolved"
    with pytest.raises(ValueError, match="not a candidate"):
        send(store, controls(MANUAL=True), trade_id, "0.25", NeverCalled(), "demo")
    store.close()


def test_unknown_trade_and_foreign_destination_are_refused(tmp_path, event):
    store, trade_id = captured(tmp_path, event)
    with pytest.raises(ValueError, match="Unknown trade"):
        send(store, controls(MANUAL=True), "no-such-trade", "0.25", NeverCalled(), "demo")
    store.update(trade_id, destination="other-account")
    with pytest.raises(ValueError, match="another destination"):
        send(store, controls(MANUAL=True), trade_id, "0.25", NeverCalled(), "demo")
    store.close()
