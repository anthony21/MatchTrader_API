import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from matchtrader.models.quotes_request import QuotesRequest


def test_quotes_request_validation_and_wire_types():
    fixtures = json.loads((Path(__file__).parents[1] / "fixtures/endpoints.json").read_text())
    payload = fixtures["quotes"]["payload"]
    request = QuotesRequest.model_validate(payload)
    assert request.wire() == payload
    with pytest.raises(ValidationError):
        QuotesRequest.model_validate({**payload, "symbols": ""})
    with pytest.raises(ValidationError):
        QuotesRequest.model_validate({**payload, "misspelledField": 1})
