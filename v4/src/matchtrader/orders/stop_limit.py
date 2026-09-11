"""Client-side STOP_LIMIT emulation; Match-Trader exposes only LIMIT, STOP and market."""

import time
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from threading import Lock
from typing import Literal

from pydantic import Field, model_validator

from ..models.base import Record


class State(StrEnum):
    ARMED = "armed"              # No broker order exists; the trigger lives in this process.
    DISPATCHING = "dispatching"  # Committed to a write; outcome unknown until it returns.
    WORKING = "working"          # A resting LIMIT is at the broker.
    FILLED = "filled"
    HELD = "held"                # Triggered but not sendable; never silently downgraded.
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Route(StrEnum):
    WAIT = "wait"                # Trigger price not reached.
    MARKET = "market"            # Triggered and marketable within the limit.
    REST_LIMIT = "rest_limit"    # Triggered past the limit; rest a passive LIMIT.
    HOLD = "hold"                # Triggered but the broker would reject the order.


class StopLimitPlan(Record):
    """A trigger price plus a worst acceptable fill price, which no native type carries."""

    instrument: str = Field(min_length=1)
    orderSide: Literal["BUY", "SELL"]
    volume: Decimal = Field(gt=0)
    stopPrice: Decimal = Field(gt=0)
    limitPrice: Decimal = Field(gt=0)
    slPrice: Decimal = Field(default=Decimal(0), ge=0)
    tpPrice: Decimal = Field(default=Decimal(0), ge=0)
    expireAfterSeconds: Decimal = Field(default=Decimal(0), ge=0)

    @model_validator(mode="after")
    def brackets_match_side(self):
        # Entry for bracket purposes is the worst price we would accept.
        entry = self.limitPrice
        if self.orderSide == "BUY" and (
            (self.slPrice and self.slPrice >= entry) or (self.tpPrice and self.tpPrice <= entry)
        ):
            raise ValueError("BUY brackets are on the wrong side of the limit price")
        if self.orderSide == "SELL" and (
            (self.slPrice and self.slPrice <= entry) or (self.tpPrice and self.tpPrice >= entry)
        ):
            raise ValueError("SELL brackets are on the wrong side of the limit price")
        return self


@dataclass(frozen=True)
class Decision:
    route: Route
    reason: str
    price: Decimal | None = None


def _trigger_price(side, quote):
    # A BUY is paid at the ask and a SELL is hit at the bid; trigger on the price actually payable.
    return Decimal(str(quote.ask)) if side == "BUY" else Decimal(str(quote.bid))


def decide(plan: StopLimitPlan, quote, *, stops_level: Decimal = Decimal(0)) -> Decision:
    """Pure trigger/route decision for one quote; no broker call and no state change."""
    market = _trigger_price(plan.orderSide, quote)
    if plan.orderSide == "BUY":
        if market < plan.stopPrice:
            return Decision(Route.WAIT, "Ask has not reached the stop price")
        marketable = market <= plan.limitPrice
        distance = market - plan.limitPrice
    else:
        if market > plan.stopPrice:
            return Decision(Route.WAIT, "Bid has not reached the stop price")
        marketable = market >= plan.limitPrice
        distance = plan.limitPrice - market
    if marketable:
        # Inside the limit right now: take it at market, which fills at or better than the limit.
        return Decision(Route.MARKET, "Triggered inside the limit price", market)
    if stops_level and distance < stops_level:
        # Too close to market to rest; sending it would only earn a broker rejection.
        return Decision(Route.HOLD, "Limit price is inside the broker stops level", plan.limitPrice)
    # Gapped through the limit: rest a passive LIMIT, which is exactly stop-limit behaviour.
    return Decision(Route.REST_LIMIT, "Triggered beyond the limit price", plan.limitPrice)


class StopLimitWatcher:
    """Drives one plan to a terminal state against an injected quote source and clock."""

    def __init__(self, api, plan: StopLimitPlan, *, quotes=None, clock=time.monotonic, journal=None):
        self.api, self.plan = api, plan
        self.quotes = quotes or (lambda: api.quotes(symbols=plan.instrument))
        self.clock, self.journal = clock, journal
        self.state, self.order_id, self.reason = State.ARMED, None, ""
        self.started = clock()
        self.lock = Lock()
        self.stops_level = Decimal(0)

    def _record(self, state, reason):
        self.state, self.reason = state, reason
        if self.journal:
            self.journal({"instrument": self.plan.instrument, "side": self.plan.orderSide,
                          "state": state.value, "reason": reason, "order_id": self.order_id})
        return state

    def load_limits(self):
        """Cache the destination stops level once so the hot path makes no extra call."""
        found = [i for i in self.api.instruments() if getattr(i, "symbol", None) == self.plan.instrument]
        if len(found) != 1:
            raise ValueError("Destination instrument is not uniquely available")
        self.stops_level = Decimal(str(found[0].stopsLevel or 0))
        return self.stops_level

    def quote(self):
        result = self.quotes()
        rows = result if isinstance(result, list) else [result]
        for row in rows:
            if getattr(row, "symbol", None) in (self.plan.instrument, None):
                return row
        raise ValueError("Quote feed returned no row for the destination instrument")

    def poll(self):
        """Evaluate one quote and act at most once; safe to call in a loop."""
        with self.lock:
            if self.state is not State.ARMED:
                return self.state
            if self.plan.expireAfterSeconds and (
                Decimal(str(self.clock() - self.started)) > self.plan.expireAfterSeconds
            ):
                return self._record(State.EXPIRED, "Trigger window elapsed before the stop price")
            decision = decide(self.plan, self.quote(), stops_level=self.stops_level)
            if decision.route is Route.WAIT:
                return self.state
            if decision.route is Route.HOLD:
                return self._record(State.HELD, decision.reason)
            # Commit the attempt before the broker write; an unknown outcome is never retried.
            self._record(State.DISPATCHING, decision.reason)
            try:
                if decision.route is Route.MARKET:
                    response = self.api.open_position(
                        instrument=self.plan.instrument, orderSide=self.plan.orderSide,
                        volume=self.plan.volume, slPrice=self.plan.slPrice, tpPrice=self.plan.tpPrice)
                    self.order_id = getattr(response, "positionId", None) or getattr(response, "orderId", None)
                    return self._record(State.FILLED, "Filled at market within the limit price")
                response = self.api.create_pending_order(
                    instrument=self.plan.instrument, orderSide=self.plan.orderSide, type="LIMIT",
                    volume=self.plan.volume, price=self.plan.limitPrice,
                    slPrice=self.plan.slPrice, tpPrice=self.plan.tpPrice)
                self.order_id = getattr(response, "orderId", None) or getattr(response, "id", None)
                return self._record(State.WORKING, "Resting LIMIT placed after the trigger")
            except Exception as error:
                # Outcome unknown: reconcile against the broker before any resubmission.
                return self._record(State.HELD, f"Dispatch outcome unknown ({type(error).__name__})")

    def run(self, *, interval=1.0, sleep=time.sleep):
        """Poll until terminal. The shared rate limiter also paces every quote read."""
        while self.poll() is State.ARMED:
            sleep(interval)
        return self.state

    def cancel(self):
        with self.lock:
            if self.state is State.ARMED:
                return self._record(State.CANCELLED, "Cancelled before the stop price was reached")
            if self.state is State.WORKING and self.order_id:
                self.api.cancel_pending_order(instrument=self.plan.instrument, id=self.order_id)
                return self._record(State.CANCELLED, "Resting LIMIT cancelled at the broker")
            return self.state
