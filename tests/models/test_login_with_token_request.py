import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.login_with_token_request import LoginWithTokenRequest


def test_login_with_token_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["login_with_token"]["payload"]
    request = LoginWithTokenRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        LoginWithTokenRequest.model_validate({**payload, "token": ""})
    with pytest.raises(ValidationError):
        LoginWithTokenRequest.model_validate({**payload, "misspelledField": 1})
