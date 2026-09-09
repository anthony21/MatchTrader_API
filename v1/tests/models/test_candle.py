from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.models.candle import Candle


def test_candle_shape_and_forward_compatible_fields():
    obj = Candle.model_validate(
        {
            "time": 1788782400000,
            "open": 1.1,
            "high": 1.12,
            "low": 1.09,
            "close": 1.11,
            "volume": 100,
            "brokerExtension": "preserved",
        }
    )
    assert obj.model_dump()["brokerExtension"] == "preserved"
    assert isinstance(obj.open, Decimal)
    with pytest.raises(ValidationError):
        Candle.model_validate({})
