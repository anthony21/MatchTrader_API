from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.models.base import Record
from matchtrader.models.open_position_request import OpenPositionRequest


def test_records_preserve_extras_but_requests_require_finite_numbers():
    assert Record.model_validate({"new": 1}).model_dump() == {"new": 1}
    with pytest.raises(ValidationError):
        OpenPositionRequest(instrument="EURUSD", orderSide="BUY", volume=Decimal("NaN"))
    with pytest.raises(ValidationError):
        OpenPositionRequest(instrument="EURUSD", orderSide="LONG", volume=1)
