from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.models.quote import Quote


def test_quote_shape_and_forward_compatible_fields():
    obj = Quote.model_validate(
        {"symbol": "EURUSD", "bid": "1.10", "ask": "1.11", "brokerExtension": "preserved"}
    )
    assert obj.model_dump()["brokerExtension"] == "preserved"
    assert isinstance(obj.bid, Decimal)
    with pytest.raises(ValidationError):
        Quote.model_validate({})
