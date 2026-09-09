"""Produce SDK request previews only; no transport is imported or acquired."""

from datetime import datetime

from ..models.create_pending_order_request import CreatePendingOrderRequest
from ..models.open_position_request import OpenPositionRequest
from .event import OrderEvent


def preview(event: OrderEvent, account_id: str, received_at: datetime, max_age_seconds: float = 30):
    base = {"mode": "shadow", "ready_for_execution": False, "event_id": event.event_id}

    def held(reason):
        return {**base, "status": "held", "reason": reason}

    if event.account_id != account_id:
        return held("account_mismatch")
    age = (received_at - event.emitted_at).total_seconds()
    if age > max_age_seconds or age < -5:
        return held("stale_or_future_timestamp")
    if event.order_type == "STOP_LIMIT":
        return held("native_stop_limit_not_verified")
    if event.action != "CREATE":
        return held("edit_cancel_require_verified_broker_order_mapping")
    if event.price is not None:
        sl, tp = event.sl_price, event.tp_price
        if event.side == "BUY":
            valid = (sl == 0 or sl < event.price) and (tp == 0 or tp > event.price)
        else:
            valid = (sl == 0 or sl > event.price) and (tp == 0 or tp < event.price)
        if not valid:
            return held("invalid_bracket_direction")
    body = {
        "instrument": event.instrument,
        "orderSide": event.side,
        "volume": event.volume_lots,
        "slPrice": event.sl_price,
        "tpPrice": event.tp_price,
    }
    if event.order_type == "MARKET":
        request = OpenPositionRequest(**body)
        operation = "open_position"
    else:
        request = CreatePendingOrderRequest(**body, price=event.price, type=event.order_type)
        operation = "create_pending_order"
    return {
        **base,
        "status": "preview",
        "operation": operation,
        "request": request.wire(),
        "remaining_checks": [
            "broker_connection",
            "instrument_mapping_precision_and_lot_rules",
            "sizing_rule",
            "existing_route_replacement",
            "durable_live_order_lifecycle",
        ],
    }
