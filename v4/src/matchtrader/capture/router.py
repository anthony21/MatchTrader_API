"""Serialized, at-most-once dispatch with explicit holds for ambiguous mappings."""

from datetime import UTC, datetime
from decimal import Decimal
from threading import RLock

from .event import CaptureEvent


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
            if duplicate:
                return {
                    "event_id": event.event_id,
                    "trade_id": row["trade_id"],
                    "status": row["decision"],
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
                "event_id": event.event_id,
                "trade_id": row["trade_id"],
                "status": status,
                "reason": reason,
                "broker_order_id": trade["broker_order_id"] if trade else "",
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
            if trade["broker_order_id"]:
                raise ValueError("Trade already has a destination order")
        elif not trade["broker_order_id"]:
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
            self._validate_instrument(api, symbol, lots, event)
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
                if p.id == position_id or (getattr(p, "orderId", None) == trade["broker_order_id"])
            ]
            if len(related) == 1:
                position_id = related[0].id
                self.store.update(identity, broker_position_id=position_id)
            order_id = trade["broker_order_id"]
            if event.action == "CANCEL":
                if order_id not in pending:
                    raise ValueError("Mapped pending order is absent; reconcile fill/cancel before acting")
                method = api.cancel_pending_order
                kwargs = {**common, "id": order_id, "type": pending[order_id].type}
            elif event.action == "EDIT" and order_id in pending:
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
        # Request IDs survive sender retries; CREATE is unique for the entire lifecycle.
        action_key = "CREATE" if event.action == "CREATE" else event.action + ":" + event.request_id
        if not self.store.claim(identity, action_key):
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
            result = method(**kwargs)
            if result.status and result.status != "OK":
                raise RuntimeError("Unrecognized broker status")
            if event.action in {"CANCEL", "CLOSE"} and result.status != "OK":
                raise RuntimeError("Explicit completion status required")
            values = {"state": "pending" if event.order_type != "MARKET" else "open"}
            if event.action == "CREATE":
                if not result.orderId and not result.positionId:
                    raise RuntimeError("Broker identity missing after submission")
                values["broker_order_id"] = result.orderId or result.positionId
                if result.positionId:
                    values["broker_position_id"] = result.positionId
            elif event.action == "CANCEL":
                # An explicit successful cancel response is broker confirmation.
                values.update(state="resolved", resolved_at=datetime.now(UTC).isoformat())
            elif event.action == "CLOSE":
                if lots == position.volume:
                    values.update(state="resolved", resolved_at=datetime.now(UTC).isoformat())
                else:
                    values["state"] = "open"
            self.store.update(identity, **values)
            self.store.finish(identity, action_key, "accepted")
            return "accepted", "Broker accepted the mapped action"
        except Exception:
            self.store.update(identity, state="uncertain")
            self.store.finish(identity, action_key, "uncertain")
            return "uncertain", "Write outcome requires broker reconciliation; not retried"

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
    def _validate_instrument(api, symbol, lots, event):
        try:
            instruments = api.instruments()
            found = [i for i in instruments if getattr(i, "symbol", None) == symbol]
            if len(found) != 1:
                raise ValueError("Destination instrument is not uniquely available")
            info = found[0].model_dump()
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
