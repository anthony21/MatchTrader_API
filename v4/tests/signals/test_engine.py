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


def test_min_box_refuses_a_tight_box_and_admits_one_at_or_above_the_minimum():
    # raw() has entry 100, sl 105, tp 95, so the box (|tp - sl|) is 10.
    with pytest.raises(Refusal, match="below the 20 minimum"):
        SignalEngine(lane(), symbols(min_box="20")).decide(parse_signal(raw()), context())
    plan = SignalEngine(lane(), symbols(min_box="10")).decide(parse_signal(raw()), context())
    assert plan.volume == Decimal("0.2")   # box exactly at the minimum is allowed


def test_sizing_modes_fixed_lots_fixed_dollar_and_percent_of_equity():
    # raw(): SELL, entry 100, sl 105 -> stop distance 5; helper instrument contractSize defaults to 1.
    fixed = SignalEngine(lane(), symbols(lots="0.2")).decide(parse_signal(raw()), context())
    assert fixed.volume == Decimal("0.2")                                 # fixed lots from the map
    dollar = SignalEngine(lane(sizing="dollar", sizing_value=Decimal("10")), symbols()).decide(
        parse_signal(raw()), context())
    assert dollar.volume == Decimal("2.0")                                # $10 / (5 * 1)
    percent = SignalEngine(lane(sizing="percent", sizing_value=Decimal("2")), symbols()).decide(
        parse_signal(raw()), context(api=Broker(equity="1000")))
    assert percent.volume == Decimal("4.0")                               # 2% of 1000 = $20; /5 = 4 lots
    # Paper needs no broker, so sizing that needs equity is not consulted; the map's lots stand.
    paper = SignalEngine(lane(sizing="percent", sizing_value=Decimal("2")), symbols()).decide(
        parse_signal(raw()), context(mode="paper", api=None, verified=False))
    assert paper.volume == Decimal("0.2")


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
    # A sell stop rests below the bid (99): 98 is a valid stop, 100 would trigger on contact.
    assert engine.decide(parse_signal(raw(orderType="STOP", entry=98, stopLoss=103, takeProfit=93)), context()).order_type == "STOP"
    with pytest.raises(Refusal, match="no supported order type"):
        engine.decide(parse_signal(raw()), context())
    entry = SignalEngine(lane(), symbols("ENTRY"))
    assert entry.decide(parse_signal(raw(side="long", entry=98, stopLoss=95, takeProfit=105)), context()).order_type == "LIMIT"
    assert entry.decide(parse_signal(raw(side="long", entry=103, stopLoss=95, takeProfit=110)), context()).order_type == "STOP"
    assert entry.decide(parse_signal(raw(side="short", entry=97, stopLoss=105, takeProfit=90)), context()).order_type == "STOP"
    assert entry.decide(parse_signal(raw(orderType="STOP", entry=98, stopLoss=103, takeProfit=93)), context()).order_type == "STOP"   # the sender's own type wins
    with pytest.raises(Refusal, match="Paper preview"):
        entry.decide(parse_signal(raw()), context(mode="paper"))
    stale = Broker()
    stale.quote_time -= 60000
    with pytest.raises(Refusal, match="fresh timestamped"):
        entry.decide(parse_signal(raw()), context(api=stale))
    with pytest.raises(Refusal, match="ambiguous"):
        entry.decide(parse_signal(raw(entry=99)), context())   # a SELL at the bid


def test_lane_grades_gate_graded_signals_and_ignore_ungraded_ones():
    engine = SignalEngine(lane(source="R01", accepted_grades=["PRIME", "STRONG"]), symbols())
    with pytest.raises(Refusal, match="Grade WEAK is not accepted"):
        engine.decide(parse_signal(raw(source="R01", grade="WEAK", detail="resting limit at range edge")), context())
    plan = engine.decide(parse_signal(raw(source="R01", grade="PRIME", detail="resting limit at range edge")), context())
    assert plan.order_type == "LIMIT"
    chain = SignalEngine(lane(accepted_grades=["PRIME"]), symbols())
    assert chain.decide(parse_signal(raw()), context()).order_type == "LIMIT"   # a chain signal has no grade


def test_lane_dollar_risk_sizes_lots_from_the_stop_distance_and_contract_size():
    engine = SignalEngine(lane(risk_usd=Decimal("5")), symbols())
    plan = engine.decide(parse_signal(raw(entry=100, stopLoss=105, takeProfit=95)), context())
    assert plan.volume == Decimal("1.0")            # 5 / (5 points * contract 1) = 1.0, step 0.1
    plan = engine.decide(parse_signal(raw(entry=100, stopLoss=160, takeProfit=40)), context())
    assert plan.volume == Decimal("0.1")            # 0.083 floors below the minimum, so the minimum
    paper = engine.decide(parse_signal(raw()), context(mode="paper", api=None, verified=False))
    assert paper.volume == Decimal("0.2")           # paper has no instrument record: the map's lots


def test_a_resting_order_already_through_the_market_is_refused_on_a_fresh_quote():
    engine = SignalEngine(lane(), symbols())
    # quote 99/101: a SELL limit at 98 sits below the bid and would fill on contact.
    with pytest.raises(Refusal, match="through the market"):
        engine.decide(parse_signal(raw(entry=98, stopLoss=103, takeProfit=93)), context())
    # a BUY limit at 102 is above the ask: same refusal.
    with pytest.raises(Refusal, match="through the market"):
        engine.decide(parse_signal(raw(side="long", entry=102, stopLoss=97, takeProfit=107)), context())
    # a SELL stop at 100 is above the bid 99: it would trigger at once.
    with pytest.raises(Refusal, match="through the market"):
        SignalEngine(lane(), symbols("STOP")).decide(parse_signal(raw()), context())
    # a stale quote stands the check down rather than judging on it; paper never reads one.
    stale = Broker()
    stale.quote_time -= 60000
    assert engine.decide(parse_signal(raw(entry=98, stopLoss=103, takeProfit=93)), context(api=stale)).price == Decimal("98")
    assert engine.decide(parse_signal(raw(entry=98, stopLoss=103, takeProfit=93)), context(mode="paper")).price == Decimal("98")


def test_attribution_is_checked_by_the_signal_shape_inside_the_decision():
    with pytest.raises(Refusal, match="X17"):
        SignalEngine(lane(x17_only=True), symbols()).decide(parse_signal(raw()), context())
    plan = SignalEngine(lane(x17_only=True), symbols()).decide(parse_signal(raw(detail="x17-spine bar=1")), context())
    assert plan.order_type == "LIMIT"
