from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.models.order import Order


def test_order_shape_and_forward_compatible_fields():
    obj = Order.model_validate(
        {
            "id": "W1",
            "symbol": "EURUSD",
            "side": "BUY",
            "volume": "0.01",
            "openPrice": "1.10",
            "type": "LIMIT",
            "activationPrice": "1.09",
            "brokerExtension": "preserved",
        }
    )
    assert obj.model_dump()["brokerExtension"] == "preserved"
    assert isinstance(obj.volume, Decimal)
    with pytest.raises(ValidationError):
        Order.model_validate({})
