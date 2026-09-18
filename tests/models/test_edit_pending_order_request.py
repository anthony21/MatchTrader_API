import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.edit_pending_order_request import EditPendingOrderRequest


def test_edit_pending_order_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["edit_pending_order"]["payload"]
    request = EditPendingOrderRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        EditPendingOrderRequest.model_validate({**payload, "volume": 0})
    with pytest.raises(ValidationError):
        EditPendingOrderRequest.model_validate({**payload, "misspelledField": 1})
