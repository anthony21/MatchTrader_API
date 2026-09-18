import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.create_pending_order_request import CreatePendingOrderRequest


def test_create_pending_order_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["create_pending_order"]["payload"]
    request = CreatePendingOrderRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        CreatePendingOrderRequest.model_validate({**payload, "volume": 0})
    with pytest.raises(ValidationError):
        CreatePendingOrderRequest.model_validate({**payload, "misspelledField": 1})
