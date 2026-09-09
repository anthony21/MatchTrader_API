from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.models.instrument import Instrument


def test_instrument_shape_and_forward_compatible_fields():
    obj = Instrument.model_validate({"symbol": "EURUSD", "volumeMin": 0.01, "brokerExtension": "preserved"})
    assert obj.model_dump()["brokerExtension"] == "preserved"
    assert isinstance(obj.volumeMin, Decimal)
    with pytest.raises(ValidationError):
        Instrument.model_validate({})
