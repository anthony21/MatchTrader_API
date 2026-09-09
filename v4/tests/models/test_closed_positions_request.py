import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.closed_positions_request import ClosedPositionsRequest


def test_closed_positions_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["closed_positions"]["payload"]
    request = ClosedPositionsRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        ClosedPositionsRequest.model_validate({**payload, "from": "2026-09-09T00:00:00Z"})
    with pytest.raises(ValidationError):
        ClosedPositionsRequest.model_validate({**payload, "misspelledField": 1})
