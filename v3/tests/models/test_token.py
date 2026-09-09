import pytest
from pydantic import ValidationError

from matchtrader.models.token import Token


def test_token_shape_and_forward_compatible_fields():
    obj = Token.model_validate({"token": "hidden-token", "brokerExtension": "preserved"})
    assert obj.model_dump()["brokerExtension"] == "preserved"
    assert "hidden-token" not in obj.model_dump_json()
    with pytest.raises(ValidationError):
        Token.model_validate({})
