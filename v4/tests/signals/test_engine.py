from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from matchtrader.signals import Refusal, SignalEngine, parse_signal
from tests.signals.helpers import Broker, context, lane, raw, symbols


def test_engine_turns_a_valid_intent_into_the_exact_broker_request():
    plan = SignalEngine(lane(), symbols()).decide(parse_signal(raw()), context())
    assert plan.method == "create_pending_order"
    assert plan.request() == {"instrument": "NAS100", "orderSide": "SELL", "volume": Decimal("0.2"),
                              "slPrice": Decimal("105"), "tpPrice": Decimal("95"), "type": "LIMIT",
                              "price": Decimal("100")}
    assert plan.label == "box" and plan.scope == ("qt", "chain", "", "", "US TECH 100", "box")
    market = SignalEngine(lane(), symbols("MARKET")).decide(parse_signal(raw()), context())
    assert market.method == "open_position" and "price" not in market.request()


@pytest.mark.parametrize("changes,ctx,reason", [
    ({}, {"armed": False}, "copying is off"),
    ({}, {"destination": "other"}, "Connect the configured"),
    ({}, {"verified": False}, "Connect the configured"),
    ({"machineId": "x"}, {}, "machine/source"),
    ({"source": "panel"}, {}, "machine/source"),
    ({"timestampUtc": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}, {}, "stale"),
    ({"label": ""}, {}, "labeled lifecycle"),
    ({}, {"ended_in_batch": True}, "ended lifecycle"),
    ({}, {"later_end_recorded": True}, "later ended"),
    ({}, {"already_attempted": True}, "already has a broker attempt"),
    ({}, {"bridge_request_exists": True}, "bridge request"),
    ({"symbol": "other"}, {}, "symbol mapping"),
    ({"side": ""}, {}, "needs a side"),
    ({"entry": 0}, {}, "needs a side"),
    ({"stopLoss": 90}, {}, "bracket"),
])
def test_engine_refuses_with_the_reason_that_names_the_failed_check(changes, ctx, reason):
    with pytest.raises(Refusal, match=reason):
        SignalEngine(lane(), symbols()).decide(parse_signal(raw(**changes)), context(**ctx))


def test_no_lane_means_copying_is_off():
    with pytest.raises(Refusal, match="copying is off"):
        SignalEngine(None, symbols()).decide(parse_signal(raw()), context())


def test_engine_reads_the_destination_limits_before_a_live_write_but_not_for_paper():
    with pytest.raises(Refusal, match="lot limits"):
        SignalEngine(lane(), symbols(lots="0.21")).decide(parse_signal(raw()), context())
    plan = SignalEngine(lane(), symbols(lots="0.21")).decide(
        parse_signal(raw()), context(mode="paper", api=None, verified=False))
    assert plan.volume == Decimal("0.21")


def test_engine_resolves_order_type_from_map_source_or_destination_quote():
    engine = SignalEngine(lane(), symbols("SOURCE"))
    assert engine.decide(parse_signal(raw(orderType="STOP")), context()).order_type == "STOP"
    with pytest.raises(Refusal, match="no supported order type"):
        engine.decide(parse_signal(raw()), context())
    entry = SignalEngine(lane(), symbols("ENTRY"))
    assert entry.decide(parse_signal(raw(side="long", entry=98, stopLoss=95, takeProfit=105)), context()).order_type == "LIMIT"
    assert entry.decide(parse_signal(raw(side="long", entry=103, stopLoss=95, takeProfit=110)), context()).order_type == "STOP"
    assert entry.decide(parse_signal(raw(side="short", entry=97, stopLoss=105, takeProfit=90)), context()).order_type == "STOP"
    assert entry.decide(parse_signal(raw(orderType="STOP")), context()).order_type == "STOP"   # the sender's own type wins
    with pytest.raises(Refusal, match="Paper preview"):
        entry.decide(parse_signal(raw()), context(mode="paper"))
    stale = Broker()
    stale.quote_time -= 60000
    with pytest.raises(Refusal, match="fresh timestamped"):
        entry.decide(parse_signal(raw()), context(api=stale))
    with pytest.raises(Refusal, match="ambiguous"):
        entry.decide(parse_signal(raw(entry=99)), context())   # a SELL at the bid


def test_attribution_is_checked_by_the_signal_shape_inside_the_decision():
    with pytest.raises(Refusal, match="X17"):
        SignalEngine(lane(x17_only=True), symbols()).decide(parse_signal(raw()), context())
    plan = SignalEngine(lane(x17_only=True), symbols()).decide(parse_signal(raw(detail="x17-spine bar=1")), context())
    assert plan.order_type == "LIMIT"
