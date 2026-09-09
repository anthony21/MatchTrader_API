import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.login_request import LoginRequest


def test_login_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["login"]["payload"]
    request = LoginRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        LoginRequest.model_validate({**payload, "password": ""})
    with pytest.raises(ValidationError):
        LoginRequest.model_validate({**payload, "misspelledField": 1})


def test_friendly_login_names_serialize_to_documented_json_keys():
    request = LoginRequest(username="user@example.com", password="local-test", brokerid="broker-test")
    assert request.wire() == {
        "email": "user@example.com",
        "password": "local-test",
        "brokerId": "broker-test",
    }
