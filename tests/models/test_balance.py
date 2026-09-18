from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.models.balance import Balance


def test_balance_shape_and_forward_compatible_fields():
    obj = Balance.model_validate(
        {"balance": "1000.01", "equity": "999.99", "currency": "USD", "brokerExtension": "preserved"}
    )
    assert obj.model_dump()["brokerExtension"] == "preserved"
    assert isinstance(obj.balance, Decimal)
    with pytest.raises(ValidationError):
        Balance.model_validate({})
