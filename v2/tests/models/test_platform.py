import pytest
from pydantic import ValidationError

from matchtrader.models.platform import Platform


def test_platform_shape_and_forward_compatible_fields():
    obj = Platform.model_validate(
        {
            "partnerId": "broker-1",
            "platformUrl": "https://broker.example",
            "brokerName": "Demo",
            "brokerExtension": "preserved",
        }
    )
    assert obj.model_dump()["brokerExtension"] == "preserved"
    with pytest.raises(ValidationError):
        Platform.model_validate({})
