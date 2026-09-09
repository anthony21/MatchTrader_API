import pytest
from pydantic import ValidationError

from matchtrader.models.authentication import Authentication


def test_authentication_shape_and_forward_compatible_fields():
    obj = Authentication.model_validate(
        {
            "token": "session-test",
            "tradingAccounts": [
                {
                    "tradingAccountId": "123",
                    "uuid": "account-uuid",
                    "tradingApiToken": "trading-test",
                    "tradingAccountToken": {"token": "account-test"},
                    "offer": {"system": {"uuid": "system-1"}},
                }
            ],
            "brokerExtension": "preserved",
        }
    )
    assert obj.model_dump()["brokerExtension"] == "preserved"
    assert "session-test" not in obj.model_dump_json()
    assert "trading-test" not in obj.model_dump_json()
    with pytest.raises(ValidationError):
        Authentication.model_validate({})


def test_selected_account_variant_keeps_nested_tokens_secret():
    account = {
        "tradingAccountId": "123",
        "tradingApiToken": "private-trading-token",
        "tradingAccountToken": {"token": "private-cookie"},
    }
    obj = Authentication.model_validate(
        {"token": "private-session", "accounts": [account], "selectedAccount": account}
    )
    assert obj.selectedAccount.tradingAccountId == "123"
    assert "private-" not in obj.model_dump_json()
    assert "private-" not in repr(obj)
