import base64
import json

import httpx
import pytest

from matchtrader.core.errors import (
    APIError,
    AuthenticationError,
    ProtocolError,
    UnknownOutcomeError,
    WritesDisabledError,
)

BALANCE = {"balance": "10.01", "equity": "9.99", "currency": "USD"}


@pytest.mark.parametrize("status", [200, 204])
def test_empty_cancel_accepts_only_verified_204_contract(api_factory, status):
    def handler(request):
        if request.url.path.endswith("/pending-order/cancel"):
            return httpx.Response(status)

    api, seen = api_factory(handler)
    values = {"id": "broker1", "instrument": "EURUSD", "orderSide": "BUY", "type": "LIMIT"}
    if status == 204:
        assert api.cancel_pending_order(**values).status == "OK"
    else:
        with pytest.raises(ProtocolError):
            api.cancel_pending_order(**values)
    assert len([r for r in seen if r.url.path.endswith("/cancel")]) == 1


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"exp": None},
        {"exp": True},
        {"exp": "1800000000"},
        {"exp": 10**30},
        {"exp": float("nan")},
        [],
        {"exp": float("inf")},
    ],
)
def test_unknown_token_expiry_has_no_assumed_duration(api_factory, claims):
    api, _ = api_factory()
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    api.connection._session_token = f"header.{encoded}.signature"
    assert api.connection.session_expires_at is None


def test_expiration_tracks_current_session_and_close(api_factory):
    api, _ = api_factory()
    assert api.connection.session_expires_at is None
    for epoch, expected in [(0, "1970-01-01T00:00:00+00:00"), (1800000000, "2027-01-15T08:00:00+00:00")]:
        encoded = base64.urlsafe_b64encode(json.dumps({"exp": epoch}).encode()).decode().rstrip("=")
        api.connection._session_token = f"header.{encoded}.signature"
        assert api.connection.session_expires_at == expected
    for malformed in ["opaque-token", "header.!.signature", "header._w.signature"]:
        api.connection._session_token = malformed
        assert api.connection.session_expires_at is None
    api.close()
    assert api.connection.session_expires_at is None


def test_sdk_identity_on_login_refresh_and_trading_reads(api_factory):
    def handler(request):
        # Reproduce the observed broker rejection of HTTPX's default identity.
        if request.headers.get("User-Agent") != "hcamm-matchtrader/0.1.0":
            return httpx.Response(403, text="challenge")
        if request.url.path.endswith("/balance"):
            return httpx.Response(200, json=BALANCE)
        if request.url.path.endswith("/refresh-token"):
            return httpx.Response(200, json={"token": "renewed-session"})

    api, seen = api_factory(handler)
    assert str(api.balance().balance) == "10.01"
    api.refresh_token()
    api.balance()
    assert [r.url.path for r in seen] == [
        "/manager/mtr-login",
        "/mtr-api/system-1/balance",
        "/manager/refresh-token",
        "/mtr-api/system-1/balance",
    ]


def test_balance_uses_selected_account_fields_and_platform_origin(api_factory, settings):
    accounts = [
        {
            "tradingAccountId": "other",
            "tradingApiToken": "other-token",
            "offer": {"system": {"uuid": "other-system"}},
        },
        {
            "tradingAccountId": "123",
            "tradingApiToken": "selected-token",
            "offer": {"system": {"uuid": "selected-system", "tradingApiDomain": "http://internal:8080"}},
        },
    ]

    def handler(request):
        if request.url.path.endswith("mtr-login"):
            return httpx.Response(
                200, json={"token": "top-level-session", "accounts": accounts, "selectedAccount": accounts[0]}
            )
        return httpx.Response(200, json=BALANCE)

    api, seen = api_factory(handler, settings.model_copy(update={"system_uuid": "", "trading_url": ""}))
    api.balance()
    request = seen[-1]
    assert str(request.url) == "https://broker.example/mtr-api/selected-system/balance"
    assert request.headers["Auth-trading-api"] == "selected-token"
    assert request.headers["Cookie"] == "co-auth=top-level-session"
    assert request.headers["Accept"] == request.headers["Content-Type"] == "application/json"
    assert not request.content


def test_auto_login_selection_and_no_untrusted_host(api_factory):
    api, seen = api_factory(
        lambda r: httpx.Response(200, json=BALANCE) if r.url.path.endswith("/balance") else None
    )
    assert str(api.balance().balance) == "10.01"
    request = seen[-1]
    assert request.url.host == "broker.example"
    assert request.url.path == "/mtr-api/system-1/balance"
    assert request.headers["Auth-trading-api"] == "trading-test"
    assert request.headers["Cookie"] == "co-auth=session-test"
    assert "Auth-trading-api" not in seen[0].headers


def test_account_cookie_mode(api_factory, settings):
    api, seen = api_factory(
        lambda r: httpx.Response(200, json=BALANCE) if r.url.path.endswith("/balance") else None,
        settings.model_copy(update={"cookie_mode": "account"}),
    )
    api.balance()
    assert seen[-1].headers["Cookie"] == "co-auth=account-test"


def test_no_implicit_multi_account_choice(api_factory, auth, settings):
    auth["tradingAccounts"].append({**auth["tradingAccounts"][0], "tradingAccountId": "456"})
    api, _ = api_factory(config=settings.model_copy(update={"account_id": ""}))
    with pytest.raises(AuthenticationError, match="exactly one"):
        api.balance()


def test_refresh_cookie_rotation_and_one_read_retry(api_factory):
    balances = [0]

    def handler(r):
        if r.url.path.endswith("/balance"):
            balances[0] += 1
            return httpx.Response(401) if balances[0] == 1 else httpx.Response(200, json=BALANCE)
        if r.url.path.endswith("/refresh-token"):
            assert "rt=refresh-test" in r.headers["Cookie"]
            return httpx.Response(200, headers={"set-cookie": "co-auth=rotated; Path=/"})

    api, seen = api_factory(handler)
    api.balance()
    assert balances[0] == 2
    assert seen[-1].headers["Cookie"] == "co-auth=rotated"


def test_second_401_ends_retry(api_factory):
    api, seen = api_factory(
        lambda r: (
            httpx.Response(401)
            if r.url.path.endswith("/balance")
            else httpx.Response(200)
            if r.url.path.endswith("/refresh-token")
            else None
        )
    )
    with pytest.raises(AuthenticationError):
        api.balance()
    assert sum(r.url.path.endswith("/balance") for r in seen) == 2


def test_mutation_timeout_not_retried(api_factory):
    def handler(r):
        if r.url.path.endswith("/position/open"):
            raise httpx.ReadTimeout("request body might contain credentials")

    api, seen = api_factory(handler)
    with pytest.raises(UnknownOutcomeError) as error:
        api.open_position(instrument="EURUSD", orderSide="BUY", volume=0.01)
    assert "credentials" not in str(error.value)
    assert sum(r.url.path.endswith("/position/open") for r in seen) == 1


def test_plaintext_errors_do_not_leak_tokens(api_factory):
    api, _ = api_factory(
        lambda r: (
            httpx.Response(410, text="session-test not-a-secret") if r.url.path.endswith("/balance") else None
        )
    )
    with pytest.raises(APIError) as error:
        api.balance()
    assert error.value.status_code == 410
    assert "session-test" not in str(error.value)


def test_writes_disabled_before_network(api_factory, settings):
    api, seen = api_factory(config=settings.model_copy(update={"enable_writes": False}))
    with pytest.raises(WritesDisabledError):
        api.open_position(instrument="EURUSD", orderSide="BUY", volume=1)
    assert seen == []


def test_malformed_response_and_business_rejection(api_factory):
    results = [httpx.Response(200, text="not json"), httpx.Response(200, json={"status": "REJECTED"})]
    api, _ = api_factory(lambda r: results.pop(0) if r.url.path.endswith("/balance") else None)
    with pytest.raises(ProtocolError):
        api.balance()
    with pytest.raises(APIError):
        api.balance()


def test_discovery_when_broker_id_is_missing(api_factory, settings):
    def handler(r):
        if r.url.path == "/manager/platform-details":
            return httpx.Response(200, json={"partnerId": "discovered"})
        if r.url.path.endswith("/balance"):
            return httpx.Response(200, json=BALANCE)

    api, seen = api_factory(handler, settings.model_copy(update={"broker_id": ""}))
    api.balance()
    import json

    assert json.loads(seen[1].content)["brokerId"] == "discovered"


def test_missing_credentials_do_not_connect(api_factory, settings):
    api, seen = api_factory(config=settings.model_copy(update={"email": ""}))
    with pytest.raises(AuthenticationError, match="MTR_EMAIL"):
        api.balance()
    assert not seen


def test_expired_session_refreshes_once_before_read(api_factory):
    def handler(r):
        if r.url.path.endswith("/refresh-token"):
            return httpx.Response(200, json={"token": "renewed"})
        if r.url.path.endswith("/balance"):
            return httpx.Response(401)

    api, seen = api_factory(handler)
    api.login()
    api.connection._expires = 0
    with pytest.raises(AuthenticationError):
        api.balance()
    assert sum(r.url.path.endswith("/refresh-token") for r in seen) == 1


def test_refresh_budget_caps_failed_attempts(api_factory):
    api, seen = api_factory(lambda r: httpx.Response(401) if r.url.path.endswith("/refresh-token") else None)
    api.login()
    for _ in range(4):
        with pytest.raises(AuthenticationError):
            api.refresh_token()
    with pytest.raises(AuthenticationError, match="four attempts"):
        api.refresh_token()
    assert sum(r.url.path.endswith("/refresh-token") for r in seen) == 4


def test_mutation_401_not_replayed(api_factory):
    api, seen = api_factory(lambda r: httpx.Response(401) if r.url.path.endswith("/position/open") else None)
    with pytest.raises(AuthenticationError):
        api.open_position(instrument="EURUSD", orderSide="BUY", volume=0.01)
    assert len(seen) == 2


def test_invalid_account_selection_clears_previous_auth(api_factory, auth):
    api, _ = api_factory()
    api.login()
    auth["tradingAccounts"][0]["tradingAccountId"] = "wrong"
    with pytest.raises(AuthenticationError):
        api.login()
    assert api.connection._trading_token == ""


def test_selected_account_only_login_response(api_factory, auth):
    response = {"token": auth["token"], "selectedAccount": auth["tradingAccounts"][0]}
    api, seen = api_factory(
        lambda r: httpx.Response(200, json=response) if r.url.path.endswith("mtr-login") else None
    )
    result = api.login()
    assert result.selectedAccount.tradingAccountId == "123"
    assert api.connection.account_id == "123"
    assert len(seen) == 1


def test_full_refresh_response_rotates_selected_account_tokens(api_factory, auth):
    import copy

    refreshed = copy.deepcopy(auth)
    refreshed["token"] = "new-session"
    refreshed["accounts"] = refreshed.pop("tradingAccounts")
    refreshed["accounts"][0]["tradingApiToken"] = "new-trading-token"
    refreshed["selectedAccount"] = refreshed["accounts"][0]

    def handler(request):
        if request.url.path.endswith("refresh-token"):
            assert "rt=refresh-test" in request.headers["Cookie"]
            assert request.headers["Content-Type"] == "application/json"
            return httpx.Response(200, json=refreshed)
        if request.url.path.endswith("balance"):
            return httpx.Response(200, json=BALANCE)

    api, seen = api_factory(handler)
    api.login()
    api.connection._expires = 0
    api.balance()
    assert seen[-1].headers["Cookie"] == "co-auth=new-session"
    assert seen[-1].headers["Auth-trading-api"] == "new-trading-token"


def test_optional_login_renewal_replaces_session_and_all_selected_tokens(api_factory, settings, auth):
    import copy
    import json

    calls = 0

    def handler(request):
        nonlocal calls
        if request.url.path.endswith("mtr-login"):
            calls += 1
            assert json.loads(request.content)["brokerId"] == "broker-1"
            response = copy.deepcopy(auth)
            response["token"] = f"session-{calls}"
            response["accounts"] = response.pop("tradingAccounts")
            response["accounts"][0]["tradingApiToken"] = f"trading-{calls}"
            response["selectedAccount"] = response["accounts"][0]
            return httpx.Response(200, json=response)
        if request.url.path.endswith("balance"):
            return httpx.Response(200, json=BALANCE)

    api, seen = api_factory(handler, settings.model_copy(update={"session_renewal": "login"}))
    api.login()
    api.connection._expires = 0
    api.balance()
    assert calls == 2
    assert seen[-1].headers["Cookie"] == "co-auth=session-2"
    assert seen[-1].headers["Auth-trading-api"] == "trading-2"
    assert all("refresh-token" not in str(r.url) for r in seen)


def test_login_renewal_has_one_read_retry_and_never_replays_mutations(api_factory, settings):
    config = settings.model_copy(update={"session_renewal": "login"})
    api, seen = api_factory(lambda r: httpx.Response(401) if r.url.path.endswith("balance") else None, config)
    with pytest.raises(AuthenticationError):
        api.balance()
    assert sum(r.url.path.endswith("mtr-login") for r in seen) == 2
    assert sum(r.url.path.endswith("balance") for r in seen) == 2
    api.close()
    api, seen = api_factory(
        lambda r: httpx.Response(401) if r.url.path.endswith("position/open") else None, config
    )
    with pytest.raises(AuthenticationError):
        api.open_position(instrument="EURUSD", orderSide="BUY", volume=0.01)
    assert sum(r.url.path.endswith("mtr-login") for r in seen) == 1
    assert sum(r.url.path.endswith("position/open") for r in seen) == 1


def test_failed_login_renewals_share_four_attempt_budget(api_factory, settings):
    fail = False

    def handler(request):
        if fail and request.url.path.endswith("mtr-login"):
            return httpx.Response(401)

    api, seen = api_factory(handler, settings.model_copy(update={"session_renewal": "login"}))
    api.login()
    fail = True
    api.connection._expires = 0
    for _ in range(4):
        with pytest.raises(AuthenticationError):
            api.balance()
    with pytest.raises(AuthenticationError, match="four attempts"):
        api.balance()
    assert len(seen) == 5
