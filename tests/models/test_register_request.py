import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.register_request import RegisterRequest


def test_register_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["register"]["payload"]
    request = RegisterRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        RegisterRequest.model_validate({**payload, "password": ""})
    with pytest.raises(ValidationError):
        RegisterRequest.model_validate({**payload, "misspelledField": 1})
