import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.close_position_request import ClosePositionRequest


def test_close_position_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["close_position"]["payload"]
    request = ClosePositionRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        ClosePositionRequest.model_validate({**payload, "volume": 0})
    with pytest.raises(ValidationError):
        ClosePositionRequest.model_validate({**payload, "misspelledField": 1})
