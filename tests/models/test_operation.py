import pytest
from pydantic import ValidationError

from matchtrader.models.operation import Operation


def test_operation_shape_and_forward_compatible_fields():
    obj = Operation.model_validate(
        {
            "status": "OK",
            "nativeCode": None,
            "errorMessage": "",
            "orderId": "W1",
            "brokerExtension": "preserved",
        }
    )
    assert obj.model_dump()["brokerExtension"] == "preserved"
    with pytest.raises(ValidationError):
        Operation.model_validate({})


def test_aqua_order_id_only_response_is_valid():
    result = Operation.model_validate({"orderId": "broker-order-1"})
    assert result.orderId == "broker-order-1" and result.status is None
