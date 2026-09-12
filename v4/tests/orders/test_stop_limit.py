from decimal import Decimal
from types import SimpleNamespace

import pytest

from matchtrader.orders import Route, StopLimitPlan, StopLimitWatcher, decide
from matchtrader.orders.stop_limit import State


def quote(bid, ask, symbol="US500"):
    return SimpleNamespace(symbol=symbol, bid=Decimal(str(bid)), ask=Decimal(str(ask)))


def buy_plan(**overrides):
    fields = {"instrument": "US500", "orderSide": "BUY", "volume": Decimal(1),
              "stopPrice": Decimal("100.00"), "limitPrice": Decimal("100.20")}
    return StopLimitPlan(**{**fields, **overrides})


def sell_plan(**overrides):
    fields = {"instrument": "US500", "orderSide": "SELL", "volume": Decimal(1),
              "stopPrice": Decimal("100.00"), "limitPrice": Decimal("99.80")}
    return StopLimitPlan(**{**fields, **overrides})


class FakeAPI:
    def __init__(self, stops_level=0, fail=False):
        self.stops_level, self.fail = stops_level, fail
        self.positions, self.pendings, self.cancels = [], [], []

    def instruments(self):
        return [SimpleNamespace(symbol="US500", stopsLevel=Decimal(str(self.stops_level)))]

    def open_position(self, **kwargs):
        if self.fail:
            raise TimeoutError("broker timeout")
        self.positions.append(kwargs)
        return SimpleNamespace(positionId="P-1", orderId=None)

    def create_pending_order(self, **kwargs):
        if self.fail:
            raise TimeoutError("broker timeout")
        self.pendings.append(kwargs)
        return SimpleNamespace(orderId="O-1")

    def cancel_pending_order(self, **kwargs):
        self.cancels.append(kwargs)
        return SimpleNamespace(status="OK")


def test_buy_waits_until_ask_reaches_the_stop():
    assert decide(buy_plan(), quote(99.90, 99.95)).route is Route.WAIT


def test_buy_triggers_at_market_when_inside_the_limit():
    decision = decide(buy_plan(), quote(99.98, 100.00))
    assert decision.route is Route.MARKET and decision.price == Decimal("100.00")


def test_buy_gapping_past_the_limit_rests_a_passive_limit():
    # The defining stop-limit behaviour: a gap must not become an unbounded market fill.
    decision = decide(buy_plan(), quote(100.45, 100.50))
    assert decision.route is Route.REST_LIMIT and decision.price == Decimal("100.20")


def test_sell_triggers_at_market_when_inside_the_limit():
    assert decide(sell_plan(), quote(100.00, 100.02)).route is Route.MARKET


def test_sell_gapping_past_the_limit_rests_a_passive_limit():
    assert decide(sell_plan(), quote(99.50, 99.52)).route is Route.REST_LIMIT


def test_sell_waits_while_bid_is_above_the_stop():
    assert decide(sell_plan(), quote(100.10, 100.12)).route is Route.WAIT


def test_resting_inside_the_stops_level_is_held_not_sent():
    decision = decide(buy_plan(), quote(100.25, 100.30), stops_level=Decimal("0.50"))
    assert decision.route is Route.HOLD


def test_watcher_opens_a_market_position_within_the_limit():
    api = FakeAPI()
    watcher = StopLimitWatcher(api, buy_plan(), quotes=lambda: [quote(99.98, 100.00)])
    assert watcher.poll() is State.FILLED
    assert api.positions and not api.pendings
    assert watcher.order_id == "P-1"


def test_watcher_rests_a_limit_after_a_gap():
    api = FakeAPI()
    watcher = StopLimitWatcher(api, buy_plan(), quotes=lambda: [quote(100.45, 100.50)])
    assert watcher.poll() is State.WORKING
    assert api.pendings[0]["type"] == "LIMIT"
    assert api.pendings[0]["price"] == Decimal("100.20")


def test_watcher_acts_once_even_when_polled_repeatedly():
    api = FakeAPI()
    watcher = StopLimitWatcher(api, buy_plan(), quotes=lambda: [quote(99.98, 100.00)])
    for _ in range(5):
        watcher.poll()
    assert len(api.positions) == 1


def test_unknown_dispatch_outcome_holds_and_never_retries():
    api = FakeAPI(fail=True)
    watcher = StopLimitWatcher(api, buy_plan(), quotes=lambda: [quote(99.98, 100.00)])
    assert watcher.poll() is State.HELD
    assert watcher.poll() is State.HELD
    assert not api.positions


def test_reason_missing_optional_summary_key_still_holds_instead_of_raising():
    # A reason dict can legally carry only origin/code/evidence (summary is optional).
    # reason["summary"] used to raise KeyError before the HELD transition ran, leaving the
    # watcher stuck in DISPATCHING. It must still reach HELD.
    class Tagged(Exception):
        def __init__(self):
            super().__init__("rejected")
            self.reason = {"origin": "broker", "code": "REJECTED", "evidence": "broker write response"}

    class FailingAPI(FakeAPI):
        def open_position(self, **kwargs):
            raise Tagged()

    api = FailingAPI()
    watcher = StopLimitWatcher(api, buy_plan(), quotes=lambda: [quote(99.98, 100.00)])
    assert watcher.poll() is State.HELD
    assert watcher.state is State.HELD
    assert "broker/REJECTED" in watcher.reason
    assert watcher.poll() is State.HELD
    assert not api.positions


def test_journal_failure_after_broker_success_does_not_mislabel_the_outcome_as_transport():
    # The broker already confirmed the fill; only the journal callback fails afterward (the
    # DISPATCHING commit's own journal write must still succeed). That must never be reported
    # as an unverified dispatch outcome (which would misrepresent a confirmed fill as
    # unconfirmed) nor labelled 'transport' - it is our own bookkeeping.
    api = FakeAPI()

    def flaky_journal(entry):
        if entry["state"] != "dispatching":
            raise RuntimeError("disk full")

    watcher = StopLimitWatcher(
        api, buy_plan(), quotes=lambda: [quote(99.98, 100.00)], journal=flaky_journal
    )
    assert watcher.poll() is State.FILLED
    assert watcher.state is State.FILLED
    assert api.positions


def test_expiry_before_trigger_sends_nothing():
    api = FakeAPI()
    ticks = iter([0, 61])  # The constructor stamps the start; the poll reads the elapsed clock.
    watcher = StopLimitWatcher(api, buy_plan(expireAfterSeconds=Decimal(60)),
                               quotes=lambda: [quote(99.90, 99.95)], clock=lambda: next(ticks))
    assert watcher.poll() is State.EXPIRED
    assert not api.positions and not api.pendings


def test_cancel_before_trigger_touches_no_broker_order():
    api = FakeAPI()
    watcher = StopLimitWatcher(api, buy_plan(), quotes=lambda: [quote(99.90, 99.95)])
    assert watcher.cancel() is State.CANCELLED
    assert not api.cancels


def test_cancel_while_working_cancels_the_resting_limit():
    api = FakeAPI()
    watcher = StopLimitWatcher(api, buy_plan(), quotes=lambda: [quote(100.45, 100.50)])
    watcher.poll()
    assert watcher.cancel() is State.CANCELLED
    assert api.cancels[0]["id"] == "O-1"


def test_load_limits_caches_the_stops_level():
    api = FakeAPI(stops_level="0.50")
    watcher = StopLimitWatcher(api, buy_plan(), quotes=lambda: [quote(100.25, 100.30)])
    watcher.load_limits()
    assert watcher.poll() is State.HELD
    assert not api.pendings


def test_buy_brackets_must_straddle_the_limit_price():
    with pytest.raises(ValueError):
        buy_plan(slPrice=Decimal("100.50"))
    with pytest.raises(ValueError):
        buy_plan(tpPrice=Decimal("100.10"))


def test_sell_brackets_must_straddle_the_limit_price():
    with pytest.raises(ValueError):
        sell_plan(slPrice=Decimal("99.50"))


def test_run_polls_until_terminal():
    api = FakeAPI()
    prices = iter([quote(99.90, 99.95), quote(99.95, 99.99), quote(99.98, 100.00)])
    watcher = StopLimitWatcher(api, buy_plan(), quotes=lambda: [next(prices)])
    assert watcher.run(interval=0, sleep=lambda _: None) is State.FILLED
