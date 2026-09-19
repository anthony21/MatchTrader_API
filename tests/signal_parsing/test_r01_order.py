from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.models.create_pending_order_request import CreatePendingOrderRequest
from matchtrader.models.open_position_request import OpenPositionRequest
from matchtrader.signal_parsing.r01 import R01Signal
from matchtrader.signal_parsing.r01_order import r01_order_shape


@pytest.mark.parametrize(("side", "expected"), [("long", "BUY"), ("short", "SELL")])
def test_order_mapping_and_destination_settings_use_established_sdk(r01_payload, side, expected):
    r01_payload.update(side=side, grade="IGNORE_THIS", volume=200)
    signal = R01Signal.model_validate(r01_payload)
    shape = r01_order_shape(signal)
    assert shape.orderSide == expected and shape.type == "LIMIT"
    assert shape.price == signal.entry and shape.slPrice == signal.stopLoss
    assert shape.tpPrice == signal.takeProfit and shape.instrument == "BTCUSD"
    request = shape.to_request(volume=Decimal("0.2"), instrument="BTCUSD.destination")
    assert isinstance(request, CreatePendingOrderRequest)
    assert request.wire() == {
        "instrument": "BTCUSD.destination", "orderSide": expected, "type": "LIMIT",
        "volume": 0.2, "price": 81194.12000000002, "slPrice": 81209.35562500003,
        "tpPrice": 81163.64875000001, "isMobile": False,
    }
    assert signal.volume == 200 and signal.ladderGrade == "PRIME"
    assert shape.instrument == "BTCUSD"
    with pytest.raises(TypeError):
        shape.to_request(instrument="BTCUSD")
    with pytest.raises(ValidationError):
        shape.to_request(volume=Decimal(0), instrument="BTCUSD")


@pytest.mark.parametrize("kind", ["heartbeat", "cancelled", "refused", "touched", "future"])
def test_other_lifecycle_events_keep_source_without_order_projection(r01_payload, kind):
    r01_payload.update(kind=kind)
    assert r01_order_shape(R01Signal.model_validate(r01_payload)) is None


def test_local_source_and_invalid_side(r01_payload):
    r01_payload.update(source="r01Local")
    assert r01_order_shape(R01Signal.model_validate(r01_payload)) is None
    r01_payload.update(source="r01Auto", side="unexpected")
    with pytest.raises(ValueError, match="side"):
        r01_order_shape(R01Signal.model_validate(r01_payload))


def test_stop_market_and_invalid_order_type(r01_payload):
    r01_payload.update(orderType="stop")
    assert r01_order_shape(R01Signal.model_validate(r01_payload)).type == "STOP"
    r01_payload.update(orderType="market", entry=0)
    shape = r01_order_shape(R01Signal.model_validate(r01_payload))
    request = shape.to_request(volume=Decimal(1), instrument="BTCUSD")
    assert isinstance(request, OpenPositionRequest)
    assert "price" not in request.wire() and "type" not in request.wire()
    r01_payload.update(orderType="unknown")
    with pytest.raises(ValidationError):
        r01_order_shape(R01Signal.model_validate(r01_payload))
