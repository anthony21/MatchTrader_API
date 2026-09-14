"""The one place an intent becomes an order, or is refused with a reason.

`SignalEngine.decide()` takes a typed signal and the facts of the moment (mode, arming,
destination, what the store already holds) and returns an `OrderPlan` ready for the
dispatcher, or raises `Refusal`. Every check lives here: lane match, freshness, label and
attribution, duplicates and ended lifecycles, symbol map, brackets, order type, sizing and
the destination's own instrument limits.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .shapes import BaseSignal


class Refusal(ValueError):
    """A local decision not to send. The message is the reason recorded on the signal."""


@dataclass(frozen=True)
class OrderPlan:
    instrument: str
    side: str                 # BUY / SELL
    order_type: str           # MARKET / LIMIT / STOP
    volume: Decimal
    price: Decimal | None     # None for MARKET
    sl: Decimal
    tp: Decimal
    label: str
    scope: tuple

    @property
    def method(self):
        return "open_position" if self.order_type == "MARKET" else "create_pending_order"

    def request(self):
        """Exactly the keyword arguments the broker facade method takes."""
        kwargs = {"instrument": self.instrument, "orderSide": self.side, "volume": self.volume,
                  "slPrice": self.sl, "tpPrice": self.tp}
        if self.order_type != "MARKET":
            kwargs.update(type=self.order_type, price=self.price)
        return kwargs


@dataclass
class Context:
    """The facts the engine needs that live outside the signal."""
    mode: str | None                 # 'paper', 'live' or None (legacy: live)
    armed: bool
    armed_at: datetime | None
    now: datetime
    destination: str
    api: object
    verified: bool
    ended_in_batch: bool = False     # the same batch also carries this lifecycle's end
    later_end_recorded: bool = False  # the store holds an end for this lifecycle after this intent
    already_attempted: bool = False  # the store holds a broker attempt for this scoped lifecycle
    bridge_request_exists: bool = False  # the capture ledger already sent this lifecycle
    extra: dict = field(default_factory=dict)

    @property
    def paper(self):
        return self.mode == "paper"


class SignalEngine:
    def __init__(self, lane, symbols):
        self.lane, self.symbols = lane, symbols

    # ---- the decision ------------------------------------------------------------------------
    def decide(self, signal: BaseSignal, ctx: Context) -> OrderPlan:
        lane = self.lane
        if not ctx.armed or lane is None:
            raise Refusal("Live signal copying is off")
        if ctx.destination != lane.destination_account or (not ctx.paper and (not ctx.api or not ctx.verified)):
            raise Refusal("Connect the configured authenticated destination")
        if signal.machineId != lane.machine_id or signal.source not in {lane.source, *lane.additional_sources}:
            raise Refusal("Signal does not match the configured machine/source")
        if lane.connection_name and signal.source != "panel" and signal.connectionName != lane.connection_name:
            raise Refusal("Signal does not match the configured chart connection")
        age = (ctx.now - signal.timestampUtc).total_seconds()
        if not ctx.armed_at or signal.timestampUtc < ctx.armed_at or not -5 <= age <= 30:
            raise Refusal("Signal is stale or predates enabling live mode; no replay")
        if ctx.bridge_request_exists:
            raise Refusal("This lifecycle already has a bridge request; no second order")
        if not signal.label:
            raise Refusal("A labeled lifecycle is required for copying")
        try:
            signal.check_attribution(lane)
        except ValueError as error:
            raise Refusal(str(error)) from None
        if ctx.ended_in_batch:
            raise Refusal("This batch already contains an ended lifecycle")
        if ctx.later_end_recorded:
            raise Refusal("A later ended lifecycle was already recorded")
        if ctx.already_attempted:
            raise Refusal("This scoped lifecycle already has a broker attempt; no duplicate order")
        mapping = self.symbols.lookup(signal.symbol)
        if not mapping:
            raise Refusal("No configured symbol mapping")
        side = signal.side
        if side not in {"BUY", "SELL"} or min(signal.entry, signal.stopLoss, signal.takeProfit) <= 0:
            raise Refusal("Intent needs a side and positive entry, stop and target")
        self._check_brackets(side, signal.entry, signal.stopLoss, signal.takeProfit)
        order_type = self._order_type(signal, mapping, side, ctx)
        lots = mapping.lots
        if not ctx.paper:
            self._check_instrument(ctx.api, mapping.destination, lots, side, order_type)
        return OrderPlan(instrument=mapping.destination, side=side, order_type=order_type, volume=lots,
                         price=None if order_type == "MARKET" else signal.entry,
                         sl=signal.stopLoss, tp=signal.takeProfit, label=signal.label, scope=signal.scope)

    # ---- the checks --------------------------------------------------------------------------
    @staticmethod
    def _check_brackets(side, entry, sl, tp):
        if (side == "BUY" and not sl < entry < tp) or (side == "SELL" and not tp < entry < sl):
            raise Refusal("Intent bracket prices do not match its side")

    def _order_type(self, signal, mapping, side, ctx):
        stated = getattr(signal, "order_type", None) or signal.copyOrderType
        order_type = stated if mapping.order_type == "SOURCE" else mapping.order_type
        if order_type == "ENTRY" and stated in {"LIMIT", "STOP"}:
            order_type = stated
        if order_type == "ENTRY":
            order_type = self._pending_type_from_quote(signal, mapping, side, ctx)
        if order_type not in {"MARKET", "LIMIT", "STOP"}:
            raise Refusal("Source intent has no supported order type")
        return order_type

    @staticmethod
    def _pending_type_from_quote(signal, mapping, side, ctx):
        if ctx.paper:
            raise Refusal("Paper preview needs an explicit source Limit or Stop order type")
        quotes = [q for q in ctx.api.quotes(symbols=mapping.destination) if q.symbol == mapping.destination]
        if len(quotes) != 1:
            raise Refusal("A unique destination quote is required for pending entry")
        quote = quotes[0]
        bid, ask = Decimal(str(quote.bid)), Decimal(str(quote.ask))
        if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
            raise Refusal("Destination quote is invalid")
        stamp = getattr(quote, "timestampMs", None) or (getattr(quote, "timestampSec", None) or 0) * 1000
        if not stamp or not -5000 <= ctx.now.timestamp() * 1000 - stamp <= 10000:
            raise Refusal("A fresh timestamped broker quote is required")
        reference = ask if side == "BUY" else bid
        if signal.entry == reference:
            raise Refusal("Entry equals current quote; pending type is ambiguous")
        below = signal.entry < reference
        return "LIMIT" if (below if side == "BUY" else not below) else "STOP"

    @staticmethod
    def _check_instrument(api, symbol, lots, side, order_type):
        """The destination's own limits, read from the broker before any write."""
        try:
            found = [i for i in api.instruments() if getattr(i, "symbol", None) == symbol]
            if len(found) != 1:
                raise Refusal("Destination instrument is not uniquely available")
            info = found[0].model_dump()
            minimum, maximum, step = (Decimal(str(info[k])) for k in ("volumeMin", "volumeMax", "volumeStep"))
            if step <= 0 or not minimum <= lots <= maximum or lots % step != 0:
                raise Refusal("Quantity violates destination lot limits/step")
            if info.get("closeOnly"):
                raise Refusal("Destination instrument is close-only")
            if info.get("longOnly") and side == "SELL":
                raise Refusal("Destination instrument is long-only")
        except (KeyError, TypeError):
            raise Refusal("Destination instrument limits could not be verified") from None
