import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.open_position_request import OpenPositionRequest


def test_open_position_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["open_position"]["payload"]
    request = OpenPositionRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        OpenPositionRequest.model_validate({**payload, "volume": 0})
    with pytest.raises(ValidationError):
        OpenPositionRequest.model_validate({**payload, "misspelledField": 1})
