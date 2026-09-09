from matchtrader.models.session_update import SessionUpdate


def test_empty_or_account_bearing_refresh_response_is_safe():
    assert SessionUpdate.model_validate({}).token is None
    update = SessionUpdate.model_validate(
        {
            "token": "private-session",
            "selectedAccount": {"tradingAccountId": "123", "tradingApiToken": "private-trading"},
        }
    )
    assert update.selectedAccount.tradingAccountId == "123"
    assert "private-" not in update.model_dump_json()
