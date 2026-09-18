from datetime import timedelta

import pytest

from matchtrader.bridge.event import OrderEvent
from matchtrader.bridge.planner import preview


@pytest.mark.parametrize("side,kind,sl,tp", [("SELL", "LIMIT", 2410, 2380), ("BUY", "STOP", 2380, 2410)])
def test_native_pending_shape(event_payload, side, kind, sl, tp):
    event = OrderEvent(**{**event_payload, "side": side, "order_type": kind, "sl_price": sl, "tp_price": tp})
    result = preview(event, "123", event.emitted_at)
    assert result["request"] == {
        "instrument": "XAUUSD",
        "orderSide": side,
        "type": kind,
        "volume": 0.02,
        "price": 2400,
        "slPrice": sl,
        "tpPrice": tp,
        "isMobile": False,
    }
    assert not result["ready_for_execution"]


def test_market_preview(event_payload):
    event = OrderEvent(**{**event_payload, "order_type": "MARKET", "price": None})
    result = preview(event, "123", event.emitted_at)
    assert result["operation"] == "open_position"
    assert "price" not in result["request"]


@pytest.mark.parametrize(
    "change,account,delta,reason",
    [
        ({}, "456", 0, "account_mismatch"),
        ({}, "123", 31, "stale_or_future_timestamp"),
        ({}, "123", -6, "stale_or_future_timestamp"),
        ({"sl_price": 2390}, "123", 0, "invalid_bracket_direction"),
        ({"action": "EDIT"}, "123", 0, "edit_cancel_require_verified_broker_order_mapping"),
        ({"action": "CANCEL"}, "123", 0, "edit_cancel_require_verified_broker_order_mapping"),
        ({"order_type": "STOP_LIMIT", "trigger_price": 2399}, "123", 0, "native_stop_limit_not_verified"),
    ],
)
def test_held_reasons(event_payload, change, account, delta, reason):
    event = OrderEvent(**{**event_payload, **change})
    result = preview(event, account, event.emitted_at + timedelta(seconds=delta))
    assert result["reason"] == reason
    assert "request" not in result
