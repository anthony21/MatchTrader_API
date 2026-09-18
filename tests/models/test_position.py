from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.models.position import Position


def test_position_shape_and_forward_compatible_fields():
    obj = Position.model_validate(
        {
            "id": "W1",
            "symbol": "EURUSD",
            "side": "BUY",
            "volume": "0.01",
            "openPrice": "1.10",
            "brokerExtension": "preserved",
        }
    )
    assert obj.model_dump()["brokerExtension"] == "preserved"
    assert isinstance(obj.volume, Decimal)
    with pytest.raises(ValidationError):
        Position.model_validate({})
