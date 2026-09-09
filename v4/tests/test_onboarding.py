import json

import httpx


def test_existing_account_login_does_not_register_another_user(api_factory):
    api, seen = api_factory()
    with api:
        api.login()
    assert [request.url.path for request in seen] == ["/manager/mtr-login"]


def test_documented_new_user_token_flow_offline(api_factory, auth):
    def handler(request):
        if request.url.path == "/manager/user":
            return httpx.Response(200, json={"token": "one-time-test-token"})
        if request.url.path == "/manager/login/co/with-token":
            assert json.loads(request.content) == {"token": "one-time-test-token"}
            return httpx.Response(200, json={"token": auth["token"], "accounts": auth["tradingAccounts"]})

    api, seen = api_factory(handler)
    with api:
        token = api.register(
            offerId="broker-test-offer",
            partnerId="broker-1",
            email="new@example.com",
            password="test-password-only",
        )
        result = api.login_with_token(token=token.token)
        assert result.accounts[0].tradingAccountId == "123"
    assert [request.url.path for request in seen] == ["/manager/user", "/manager/login/co/with-token"]
