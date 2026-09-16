"""The one place an intent becomes an order, or is refused with a reason.

`SignalEngine.decide()` takes a typed signal and the facts of the moment (mode, arming,
destination, what the store already holds) and returns an `OrderPlan` ready for the
dispatcher, or raises `Refusal`. Every check lives here: lane match, freshness, label and
attribution, duplicates and ended lifecycles, symbol map, brackets, order type, sizing and
the destination's own instrument limits.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

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
        grade, accepted = getattr(signal, "grade", ""), getattr(lane, "accepted_grades", None) or []
        if accepted and grade and grade not in accepted:
            raise Refusal(f"Grade {grade} is not accepted by the lane")
        mapping = self.symbols.lookup(signal.symbol)
        if not mapping:
            raise Refusal("No configured symbol mapping")
        side = signal.side
        if side not in {"BUY", "SELL"} or min(signal.entry, signal.stopLoss, signal.takeProfit) <= 0:
            raise Refusal("Intent needs a side and positive entry, stop and target")
        self._check_brackets(side, signal.entry, signal.stopLoss, signal.takeProfit)
        box = abs(signal.takeProfit - signal.stopLoss)
        floor = self._min_box(lane)
        if floor and box < floor:
            raise Refusal(f"Box {box} is below the {floor} minimum box set on this copy; "
                          "tight boxes stop out on entry noise")
        order_type = self._order_type(signal, mapping, side, ctx)
        lots = mapping.lots
        entry, sl, tp = signal.entry, signal.stopLoss, signal.takeProfit
        if not ctx.paper:
            info = self._instrument(ctx.api, mapping.destination)
            # Round to the destination's price grid before the checks below, so they run on the
            # values that will actually be sent; a stop that rounds onto the entry is refused here
            # rather than dispatched. Paper keeps the source prices: it must never read the broker.
            entry, sl, tp = self._on_grid(info, entry, sl, tp)
            self._check_brackets(side, entry, sl, tp)
            equity = self._equity(ctx.api) if self._sizing(lane) == "percent" else None
            lots = self._lots(lane, mapping, signal, info, equity)
            self._check_limits(info, lots, side)
            if order_type != "MARKET":
                self._check_not_through_market(ctx, mapping.destination, side, order_type, entry)
        return OrderPlan(instrument=mapping.destination, side=side, order_type=order_type, volume=lots,
                         price=None if order_type == "MARKET" else entry,
                         sl=sl, tp=tp, label=signal.label, scope=signal.scope)

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
    def _on_grid(info, *values):
        """Round prices onto the destination instrument's own price grid: pricePrecision decimals,
        ROUND_HALF_UP. Sources publish more precision than the broker can represent (SPX500 takes
        one decimal, BTCUSD two), so send what it can rather than let it round by an unobserved rule.
        A row without pricePrecision, or a zero/None value, is left unchanged. The caller re-checks
        the bracket afterwards, since rounding can move a narrow stop onto the entry."""
        precision = info.get("pricePrecision")
        if precision is None:
            return tuple(values)
        quantum = Decimal(1).scaleb(-int(precision))
        return tuple(v if v in (None, 0) else Decimal(str(v)).quantize(quantum, rounding=ROUND_HALF_UP)
                     for v in values)

    @staticmethod
    def _instrument(api, symbol):
        """The destination's own instrument record, read from the broker before any write."""
        found = [i for i in api.instruments() if getattr(i, "symbol", None) == symbol]
        if len(found) != 1:
            raise Refusal("Destination instrument is not uniquely available")
        return found[0].model_dump()

    @staticmethod
    def _min_box(lane):
        """The minimum box (take-profit to stop-loss distance) this copy will accept, applied only
        when the lane's own switch is on. The box filter lives on the copy configuration, not on the
        symbol map, so one setting with one switch governs every instrument this copy handles. 0 or
        the switch off disables it."""
        if not getattr(lane, "min_box_enabled", False):
            return Decimal(0)
        value = getattr(lane, "min_box", None)
        return Decimal(str(value)) if value else Decimal(0)

    @staticmethod
    def _sizing(lane):
        """How this config sizes: 'lots' (the map's fixed lots), 'dollar' (a fixed dollar risk), or
        'percent' (a percent of account equity as the risk). Falls back to the old risk_usd field."""
        mode = getattr(lane, "sizing", None)
        if mode in {"lots", "dollar", "percent"}:
            return mode
        return "dollar" if getattr(lane, "risk_usd", None) else "lots"

    @staticmethod
    def _equity(api):
        """The destination account's equity, read from the broker, for percent-of-account sizing."""
        try:
            equity = Decimal(str(api.balance().equity))
        except Exception:
            raise Refusal("Percent sizing needs the account equity; the balance read failed") from None
        if not equity.is_finite() or equity <= 0:
            raise Refusal("Percent sizing needs a positive account equity")
        return equity

    @classmethod
    def _lots(cls, lane, mapping, signal, info, equity=None):
        """The map's fixed lots, or a risk (fixed dollars, or a percent of equity) divided by the
        stop distance in contract units."""
        mode = cls._sizing(lane)
        if mode == "lots":
            return mapping.lots
        value = getattr(lane, "sizing_value", None)
        if value is None:
            value = getattr(lane, "risk_usd", None)
        if not value or Decimal(str(value)) <= 0:
            raise Refusal("This config's sizing needs a positive dollar amount or percent")
        if mode == "percent":
            risk = equity * Decimal(str(value)) / Decimal(100)
        else:
            risk = Decimal(str(value))
        try:
            contract = Decimal(str(info.get("contractSize") or 1))
            step, minimum = (Decimal(str(info[k])) for k in ("volumeStep", "volumeMin"))
        except (KeyError, TypeError):
            raise Refusal("Destination contract size could not be verified for risk sizing") from None
        distance = abs(signal.entry - signal.stopLoss)
        if distance <= 0 or contract <= 0:
            raise Refusal("Risk sizing needs a positive stop distance")
        lots = (risk / (distance * contract)).quantize(step, rounding=ROUND_DOWN)
        return max(lots, minimum)

    @staticmethod
    def _check_limits(info, lots, side):
        try:
            minimum, maximum, step = (Decimal(str(info[k])) for k in ("volumeMin", "volumeMax", "volumeStep"))
        except (KeyError, TypeError):
            raise Refusal("Destination instrument limits could not be verified") from None
        if step <= 0 or not minimum <= lots <= maximum or lots % step != 0:
            raise Refusal("Quantity violates destination lot limits/step")
        if info.get("closeOnly"):
            raise Refusal("Destination instrument is close-only")
        if info.get("longOnly") and side == "SELL":
            raise Refusal("Destination instrument is long-only")

    @staticmethod
    def _check_not_through_market(ctx, symbol, side, order_type, level):
        """A resting order whose level is already through the market executes on contact at whatever
        the book is, with the stop left where it was sent. That is not the order that was asked for.
        Judged on a fresh destination quote only; without one the check stands down."""
        quotes_of = getattr(ctx.api, "quotes", None)
        if quotes_of is None:
            return
        try:
            quotes = [q for q in quotes_of(symbols=symbol) if getattr(q, "symbol", None) == symbol]
        except Exception:
            return
        if len(quotes) != 1:
            return
        quote = quotes[0]
        stamp = getattr(quote, "timestampMs", None) or (getattr(quote, "timestampSec", None) or 0) * 1000
        if not stamp or not -5000 <= ctx.now.timestamp() * 1000 - stamp <= 10000:
            return
        bid, ask = Decimal(str(quote.bid)), Decimal(str(quote.ask))
        if order_type == "STOP":
            through = level <= ask if side == "BUY" else level >= bid
        else:
            through = level >= ask if side == "BUY" else level <= bid
        if through:
            raise Refusal(f"Level {level} is already through the market ({bid}/{ask}); "
                          "a resting order would execute on contact")
