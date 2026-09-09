import pytest
from pydantic import ValidationError

from matchtrader.bridge.event import OrderEvent


@pytest.mark.parametrize(
    "change",
    [
        {"volume_lots": None},
        {"volume_lots": "NaN"},
        {"volume_lots": "0"},
        {"sl_price": None},
        {"emitted_at": "2026-09-09T10:00:00"},
        {"revision": True},
        {"price": None},
        {"extra": "ignored?"},
        {"order_type": "STOP_LIMIT"},
        {"trigger_price": "2401"},
        {"order_type": "MARKET"},
    ],
)
def test_incomplete_or_ambiguous_contract_rejected(event_payload, change):
    with pytest.raises(ValidationError):
        OrderEvent.model_validate({**event_payload, **change})


def test_stop_limit_preserves_two_prices(event_payload):
    event = OrderEvent(**{**event_payload, "order_type": "STOP_LIMIT", "trigger_price": "2399"})
    assert event.price != event.trigger_price
    assert event.order_key() == ("machine-test", "r01-test", "123", "order-1")


def test_cancel_can_omit_bracket_and_quantity(event_payload):
    event = OrderEvent(
        **{
            **event_payload,
            "action": "CANCEL",
            "volume_lots": None,
            "sl_price": None,
            "tp_price": None,
            "price": None,
        }
    )
    assert event.volume_lots is None
