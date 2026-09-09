import pytest
from pydantic import ValidationError

from matchtrader.models.account import Account


def test_account_shape_and_forward_compatible_fields():
    obj = Account.model_validate(
        {
            "tradingAccountId": "123",
            "uuid": "account-uuid",
            "tradingApiToken": "trading-test",
            "tradingAccountToken": {"token": "account-test"},
            "offer": {"system": {"uuid": "system-1"}},
            "brokerExtension": "preserved",
        }
    )
    assert obj.model_dump()["brokerExtension"] == "preserved"
    assert "session-test" not in obj.model_dump_json()
    assert "trading-test" not in obj.model_dump_json()
    with pytest.raises(ValidationError):
        Account.model_validate({})
