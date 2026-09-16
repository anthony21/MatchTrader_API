"""Serialized, at-most-once dispatch with explicit holds for ambiguous mappings."""

import logging
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from threading import RLock
from types import SimpleNamespace

from ..core.reason import local_reason, unconfirmed_reason
from ..version import EVENT_SCHEMA_VERSION
from .dispatch_metrics import mark
from .event import CaptureEvent

logger = logging.getLogger(__name__)


def _unverified(message):
    """A post-response check failed after the broker replied; never confuse this with a
    wire failure. The RuntimeError carries its own `.reason` (origin='local') so the
    generic except block in _dispatch keeps this exact message instead of discarding it."""
    error = RuntimeError(message)
    error.reason = local_reason(error)
    return error


def record_failure(store, identity, action_key, exc):
    """Land a failed or unconfirmed write attempt: persist an investigable reason, mark the
    trade uncertain and close the attempt so it is never retried. Shared by the armed router
    and the explicit manual send so both paths keep exactly the same discipline."""
    # Reason construction AND the insert both live inside this one protective region:
    # an exception whose own __str__ raises (built while forming the reason) must not
    # escape and skip the state transitions below - it must instead fall through to
    # the log statement, and the transitions must still run unconditionally.
    reason = None
    try:
        candidate = getattr(exc, "reason", None)
        if isinstance(candidate, dict) and all(
            candidate.get(k) for k in ("origin", "code", "evidence")
        ):
            reason = candidate
        else:
            # No structured evidence of where this failed (wire, broker or local):
            # asserting origin='transport' here would claim a cause never established.
            reason = unconfirmed_reason(exc, correlation=f"trade {identity} action {action_key}")
        store.record_reason(identity, action_key, 1, "uncertain", reason)
    except Exception as log_exc:
        # The row may be lost, but the explanation must survive somewhere: log it,
        # sanitized, correlated to the trade/action, rather than a silent pass.
        logger.error(
            "Outcome reason not recorded for trade_id=%s action_key=%s origin=%s code=%s: %s",
            identity, action_key,
            reason.get("origin") if isinstance(reason, dict) else "unavailable",
            reason.get("code") if isinstance(reason, dict) else "unavailable",
            type(log_exc).__name__,
        )
    store.update(identity, state="uncertain")
    store.finish(identity, action_key, "uncertain")
    return "uncertain", "Write outcome requires broker reconciliation; not retried"


class CaptureRouter:
    def __init__(self, store, route=None):
        self.store = store
        self.route = route
        self.armed = False
        self.armed_at = None
        self.demo_verified = False
        self.lock = RLock()

    def receive(self, payload, api=None, destination=""):
        event = CaptureEvent.model_validate(payload)
        with self.lock:
            row, duplicate = self.store.record(event)
            mark("event_commit")
            if duplicate:
                trade = self.store.trade(row['trade_id']) if row['trade_id'] else None
                uncertain = trade and trade['state'] in {'uncertain', 'dispatching'}
                # A crash can occur after a durable event/attempt but before its
                # terminal event decision. Recover evidence; never repeat the write.
                if row['decision'] == 'captured' and event.kind == 'ACCEPTED' and event.action != 'OBSERVE':
                    action_key = 'CREATE' if event.action == 'CREATE' else event.action + ':' + event.request_id
                    with self.store.lock:
                        attempt = self.store.db.execute(
                            'SELECT state FROM attempts WHERE trade_id=? AND action_key=?',
                            (row['trade_id'], action_key),
                        ).fetchone()
                    prior = attempt['state'] if attempt else None
                    row['decision'] = 'uncertain' if uncertain or prior in {'dispatching', 'uncertain'} else 'accepted' if prior == 'accepted' else 'held'
                    row['reason'] = 'Recovered prior attempt; no replay' if prior else 'Prior event processing incomplete; no automatic replay'
                    self.store.decision(row['seq'], row['decision'], row['reason'])
                return {
                    "schema_version": EVENT_SCHEMA_VERSION,
                    "event_id": event.event_id,
                    "trade_id": row["trade_id"],
                    "status": "uncertain" if uncertain else row["decision"],
                    "reason": "Prior dispatch needs reconciliation" if uncertain else row["reason"],
                    "broker_order_id": trade["broker_order_id"] if trade else "",
                    "broker_position_id": trade["broker_position_id"] if trade else "",
                    "duplicate": True,
                }
            status, reason = "captured", "Native observation; no broker action"
            if event.kind == "ACCEPTED" and event.action != "OBSERVE":
                try:
                    status, reason = self._dispatch(event, row["trade_id"], api, destination)
                except ValueError as exc:
                    status, reason = "held", str(exc)
                except Exception:
                    status, reason = "held", "Preflight read failed; no broker write attempted"
            self.store.decision(row["seq"], status, reason)
            trade = self.store.trade(row["trade_id"]) if row["trade_id"] else None
            return {
                "schema_version": EVENT_SCHEMA_VERSION,
                "event_id": event.event_id,
                "trade_id": row["trade_id"],
                "status": status,
                "reason": reason,
                "broker_order_id": trade["broker_order_id"] if trade else "",
                "broker_position_id": trade["broker_position_id"] if trade else "",
                "duplicate": False,
            }

    def _dispatch(self, event, identity, api, destination):
        if not self.armed or not self.route or not self.demo_verified or not api:
            raise ValueError("Copying is not armed with a verified demo destination")
        if destination != self.route.destination_account:
            raise ValueError("Selected destination does not match route")
        if event.snapshot or not -5 <= (datetime.now(UTC) - event.emitted_at).total_seconds() <= 30:
            raise ValueError("Snapshot or expired event; never replay old trades")
        if self.armed_at and event.emitted_at < self.armed_at:
            raise ValueError("Event predates enabling copying; never replay the off period")
        if not identity or not event.request_id:
            raise ValueError("Missing source trade/request identity")
        trade = self.store.trade(identity)
        # Lifecycle actions follow the original attribution of an exactly linked trade.
        routed = event.model_copy(update={"source": trade["source"]}) if event.action != "CREATE" else event
        mapping = self.route.match(routed)
        if trade["last_event_at"] and event.emitted_at < datetime.fromisoformat(trade["last_event_at"]):
            raise ValueError("Out-of-order action predates the latest dispatched action")
        if trade["state"] in {"dispatching", "uncertain", "resolved"}:
            raise ValueError("Trade is resolved or needs reconciliation; no automatic retry")
        if trade["destination"] and trade["destination"] != destination:
            raise ValueError("Trade already belongs to another destination")
        if event.action == "CREATE":
            if trade["broker_order_id"] or trade["broker_position_id"]:
                raise ValueError("Trade already has a destination order")
        elif not trade["broker_order_id"] and not trade["broker_position_id"]:
            raise ValueError("No confirmed destination mapping for this source trade")
        if not event.brackets_absolute:
            raise ValueError("Offset brackets require an explicit absolute-price conversion")
        if event.order_type not in {"MARKET", "LIMIT", "STOP"}:
            raise ValueError("Unsupported order type; stop-limit is not silently converted")
        if event.side not in {"BUY", "SELL"}:
            raise ValueError("Missing side")
        lots = event.quantity * mapping.quantity_multiplier
        symbol = mapping.destination
        if event.action in {"CREATE", "EDIT", "CLOSE"}:
            if lots <= 0 or lots > mapping.max_lots:
                raise ValueError("Converted quantity is outside route limit")
            event = self._validate_instrument(api, symbol, lots, event)
        common = {"instrument": symbol, "orderSide": event.side}
        if event.action == "CREATE":
            kwargs = {**common, "volume": lots, "slPrice": event.sl, "tpPrice": event.tp}
            if event.order_type == "MARKET":
                method = api.open_position
            else:
                method = api.create_pending_order
                kwargs.update(type=event.order_type, price=event.price)
        else:
            if trade["symbol"] != symbol or trade["side"] != event.side:
                raise ValueError("Source edit does not match mapped instrument/side")
            pending = {o.id: o for o in api.active_orders()}
            positions = self._positions(api.open_positions())
            position_id = trade["broker_position_id"]
            # Only exact broker-provided relationships; never symbol/price matching.
            related = [
                p
                for p in positions
                if (position_id and p.id == position_id)
                or (trade["broker_order_id"] and getattr(p, "orderId", None) == trade["broker_order_id"])
            ]
            related = [p for p in related if p.symbol == symbol and p.side == event.side]
            self.store.observe_positions(identity, destination, related)
            if len(related) == 1:
                position_id = related[0].id
                self.store.update(identity, broker_position_id=position_id)
            order_id = trade["broker_order_id"]
            if event.action == "CANCEL":
                if order_id not in pending:
                    raise ValueError("Mapped pending order is absent; reconcile fill/cancel before acting")
                method = api.cancel_pending_order
                kwargs = {**common, "id": order_id, "type": pending[order_id].type}
            elif event.action == "EDIT" and order_id in pending and event.order_id:
                method = api.edit_pending_order
                kwargs = {
                    **common,
                    "id": order_id,
                    "type": pending[order_id].type,
                    "volume": lots,
                    "priceOrder": event.price,
                    "slPrice": event.sl,
                    "tpPrice": event.tp,
                }
            elif len(related) == 1:
                with self.store.lock:
                    self.store.mappings.guard_position(identity)
                position = related[0]
                if event.action == "CLOSE":
                    if lots > position.volume:
                        raise ValueError("Close exceeds mapped destination position")
                    method = api.close_position if lots == position.volume else api.partial_close
                    kwargs = {**common, "positionId": position_id, "volume": lots}
                else:
                    if lots != position.volume:
                        raise ValueError("Position edit cannot change volume; use partial close")
                    method = api.edit_position
                    kwargs = {
                        **common,
                        "id": position_id,
                        "volume": lots,
                        "slPrice": event.sl,
                        "tpPrice": event.tp,
                    }
            else:
                raise ValueError("No unambiguous open-position mapping; manual reconciliation required")
        mark("preflight_end")
        # Request IDs survive sender retries; CREATE is unique for the entire lifecycle.
        action_key = "CREATE" if event.action == "CREATE" else event.action + ":" + event.request_id
        if not self.store.claim(identity, action_key, event=event, destination=destination, request=kwargs):
            raise ValueError("Action already attempted; it will not be sent again")
        self.store.update(
            identity,
            destination=destination,
            symbol=symbol,
            side=event.side,
            lots=str(lots) if event.action in {"CREATE", "EDIT"} else trade["lots"],
            order_type=event.order_type,
            last_request=event.request_id,
            last_event_at=event.emitted_at.isoformat(),
        )
        try:
            mark("attempt_commit")
            result = method(**kwargs)
            if result.status and result.status != "OK":
                raise _unverified("Unrecognized broker status")
            if event.action in {"CANCEL", "CLOSE"} and result.status != "OK":
                raise _unverified("Explicit completion status required")
            values = {"state": "pending" if event.order_type != "MARKET" else "open"}
            if event.action == "CREATE":
                if not result.orderId and not result.positionId:
                    raise _unverified("Broker identity missing after submission")
                values["broker_order_id"] = result.orderId or ""
                if result.positionId:
                    values["broker_position_id"] = result.positionId
            elif event.action == "CANCEL":
                # An explicit successful cancel response is broker confirmation.
                # Cancelling a remaining pending quantity does not close its filled position.
                if related or self.store.mappings.ids(identity, 'destination', 'position'):
                    values['state'] = 'open'
                else:
                    values.update(state="resolved", resolved_at=datetime.now(UTC).isoformat())
            elif event.action == "CLOSE":
                if lots == position.volume and order_id not in pending:
                    values.update(state="resolved", resolved_at=datetime.now(UTC).isoformat())
                else:
                    values["state"] = "pending" if order_id in pending and lots == position.volume else "open"
            try:
                self.store.update(identity, **values)
                self.store.finish(identity, action_key, "accepted")
            except Exception as local_exc:
                # The broker already confirmed the write above; anything raised from here on
                # is our own persistence code, never the wire - it must never be mislabelled
                # transport. Only attach a reason if one is not already present.
                if not isinstance(getattr(local_exc, "reason", None), dict):
                    local_exc.reason = local_reason(
                        local_exc,
                        evidence="broker accepted the write; local persistence of the accepted state failed",
                    )
                raise
            return "accepted", "Broker accepted the mapped action"
        except Exception as exc:
            return record_failure(self.store, identity, action_key, exc)

    @staticmethod
    def _positions(groups):
        result = []
        for item in groups:
            if item.positions:
                result.extend(CaptureRouter._positions(item.positions))
            else:
                result.append(item)
        return result

    @staticmethod
    def instrument_info(api, symbol):
        """Read the one destination instrument row, or refuse."""
        instruments = api.instruments()
        found = [i for i in instruments if getattr(i, "symbol", None) == symbol]
        if len(found) != 1:
            raise ValueError("Destination instrument is not uniquely available")
        return found[0].model_dump()

    @staticmethod
    def quantise_prices(info, event):
        """Return `event` with its prices on the destination's own price grid.

        Sources publish raw floats (77498.42683130718, 7656.299999999985) at the
        source platform's tick. The destination accepts `pricePrecision` decimals
        and nothing finer, so send what it can represent rather than letting the
        broker round by an unobserved rule. Zero means "no bracket" and is left
        alone. A row without `pricePrecision` is passed through unchanged.

        The caller must re-check bracket geometry afterwards: rounding can move
        a narrow stop onto the entry.
        """
        precision = info.get("pricePrecision")
        if precision is None:
            return event
        quantum = Decimal(1).scaleb(-int(precision))

        def grid(value):
            if value in (None, 0):
                return value
            return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)

        return SimpleNamespace(**{**vars(event), "price": grid(getattr(event, "price", None)),
                                  "sl": grid(getattr(event, "sl", None)),
                                  "tp": grid(getattr(event, "tp", None))})

    @staticmethod
    def _validate_instrument(api, symbol, lots, event):
        """Validate the destination instrument and return the event on its price grid.

        Prices are quantised before the bracket checks below, so the checks run on
        the values that will actually be sent.
        """
        try:
            info = CaptureRouter.instrument_info(api, symbol)
            event = CaptureRouter.quantise_prices(info, event)
            minimum, maximum, step = (Decimal(str(info[k])) for k in ("volumeMin", "volumeMax", "volumeStep"))
            if step <= 0 or not minimum <= lots <= maximum or lots % step != 0:
                raise ValueError("Quantity violates destination lot limits/step")
            if info.get("closeOnly") and event.action == "CREATE":
                raise ValueError("Destination instrument is close-only")
            if info.get("longOnly") and event.side == "SELL" and event.action == "CREATE":
                raise ValueError("Destination instrument is long-only")
            if event.action in {"CREATE", "EDIT"} and event.order_type != "MARKET":
                if event.price <= 0:
                    raise ValueError("Pending entry must be positive")
                if event.side == "BUY" and (
                    (event.sl and event.sl >= event.price) or (event.tp and event.tp <= event.price)
                ):
                    raise ValueError("BUY brackets are on the wrong side of entry")
                if event.side == "SELL" and (
                    (event.sl and event.sl <= event.price) or (event.tp and event.tp >= event.price)
                ):
                    raise ValueError("SELL brackets are on the wrong side of entry")
        except (KeyError, TypeError):
            raise ValueError("Destination instrument limits could not be verified") from None
        return event
