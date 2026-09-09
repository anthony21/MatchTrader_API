import httpx
import pytest

from matchtrader import MatchTraderAPI
from matchtrader.core.errors import ConnectionClosedError


def test_facade_owners_share_without_premature_close(api_factory, settings):
    first, _ = api_factory()
    with MatchTraderAPI(settings) as second:
        assert first.connection is second.connection
    assert not first.connection.closed
    first.close()
    first.close()
    assert first.connection.closed
    with pytest.raises(ConnectionClosedError):
        first.balance()


def test_context_closes_on_error(api_factory):
    api, _ = api_factory()
    with pytest.raises(RuntimeError), api:
        raise RuntimeError("application failure")
    assert api.closed and api.connection.closed


def test_login_uses_env_credentials_and_redacts_result(api_factory):
    api, _ = api_factory()
    result = api.login()
    assert "session-test" not in result.model_dump_json()
    assert "trading-test" not in result.model_dump_json()


def test_facade_stream_lifecycle_and_analysis(api_factory, monkeypatch):
    from unittest.mock import Mock

    from matchtrader.core.websocket_connection import WebSocketConnection

    socket = Mock()
    acquire = Mock(return_value=socket)
    monkeypatch.setattr(WebSocketConnection, "acquire", acquire)
    api, _ = api_factory()
    assert api.websocket() is api.websocket()
    acquire.assert_called_once()
    assert api.dataframe([{"symbol": "EURUSD"}]).symbol.iloc[0] == "EURUSD"
    assert api.analyze_closed_operations([])["operations"] == 0
    api.close()
    socket.release.assert_called_once()
    with pytest.raises(ConnectionClosedError):
        api.websocket()


def test_concurrent_facade_acquisition_uses_one_session(api_factory, settings):
    from concurrent.futures import ThreadPoolExecutor

    owner, _ = api_factory()

    def borrow(_):
        with MatchTraderAPI(settings) as child:
            assert child.connection is owner.connection
            return id(child.connection)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(borrow, range(20)))) == 1
    assert owner.connection._leases == 1


def test_multiple_accounts_tokens_refresh_and_cleanup_are_isolated(settings):
    calls = {"123": [], "456": []}

    def transport(account):
        def handle(request):
            calls[account].append(request)
            if request.url.path.endswith("/mtr-login"):
                accounts = [
                    {
                        "tradingAccountId": a,
                        "tradingApiToken": "trade-" + a,
                        "tradingAccountToken": {"token": "cookie-" + a},
                        "offer": {"system": {"uuid": "system-" + a}},
                    }
                    for a in calls
                ]
                return httpx.Response(
                    200,
                    json={"token": "session-" + account, "tradingAccounts": accounts},
                    headers={"set-cookie": "rt=refresh-" + account + "; Path=/manager"},
                )
            if request.url.path.endswith("/refresh-token"):
                assert "rt=refresh-" + account in request.headers["Cookie"]
                return httpx.Response(200, json={"token": "renewed-" + account})
            assert request.url.path == "/mtr-api/system-" + account + "/balance"
            assert request.headers["Auth-trading-api"] == "trade-" + account
            return httpx.Response(200, json={"balance": account, "equity": account, "currency": "USD"})

        return httpx.MockTransport(handle)

    with MatchTraderAPI(settings, transport=transport("123")) as first:
        with first.for_account("456", transport=transport("456")) as second:
            assert first.connection is not second.connection
            assert first.connection._limiter is second.connection._limiter
            assert str(first.balance().balance) == "123"
            assert str(second.balance().balance) == "456"
            first.refresh_token()
            first.balance()
            second.balance()
            assert calls["123"][-1].headers["Cookie"] == "co-auth=renewed-123"
            assert calls["456"][-1].headers["Cookie"] == "co-auth=session-456"
            frame = second.account_dataframe([second.balance()])
            assert frame.mtr_account_id.tolist() == ["456"]
            assert frame.mtr_platform_url.tolist() == [settings.platform_url]
        assert second.connection.closed
        assert not first.connection.closed
        first.balance()


def test_account_factory_reuses_same_identity_and_clears_stream_credentials(api_factory):
    from matchtrader.core.errors import ConfigurationError

    api, _ = api_factory()
    with api.for_account("123") as same:
        assert same.connection is api.connection
    with api.for_account("456") as other:
        assert other.settings.system_uuid == ""
        assert other.settings.ws_url == ""
        assert other.settings.ws_headers_json.get_secret_value() == "{}"
    with pytest.raises(ConfigurationError):
        api.for_account("")
    with pytest.raises(ConfigurationError):
        api.account_dataframe([{"mtr_account_id": "wrong"}])
    api.close()
    with pytest.raises(ConnectionClosedError):
        api.for_account("456")


def test_different_brokers_do_not_share_same_account_number(api_factory, settings):
    first, _ = api_factory()
    with MatchTraderAPI(settings.model_copy(update={"platform_url": "https://other.example"})) as other:
        assert first.connection is not other.connection
