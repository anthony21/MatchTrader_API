import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.candles_request import CandlesRequest


def test_candles_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["candles"]["payload"]
    request = CandlesRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        CandlesRequest.model_validate({**payload, "from": "2026-09-09T00:00:00Z"})
    with pytest.raises(ValidationError):
        CandlesRequest.model_validate({**payload, "misspelledField": 1})
