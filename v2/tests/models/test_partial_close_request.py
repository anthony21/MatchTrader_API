import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.partial_close_request import PartialCloseRequest


def test_partial_close_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["partial_close"]["payload"]
    request = PartialCloseRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        PartialCloseRequest.model_validate({**payload, "volume": 0})
    with pytest.raises(ValidationError):
        PartialCloseRequest.model_validate({**payload, "misspelledField": 1})
