import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.cancel_pending_order_request import CancelPendingOrderRequest


def test_cancel_pending_order_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["cancel_pending_order"]["payload"]
    request = CancelPendingOrderRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        CancelPendingOrderRequest.model_validate({**payload, "password": ""})
    with pytest.raises(ValidationError):
        CancelPendingOrderRequest.model_validate({**payload, "misspelledField": 1})
