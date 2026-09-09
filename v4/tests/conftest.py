import json
import socket
from pathlib import Path

import httpx
import pytest

from matchtrader import MatchTraderAPI, Settings
from matchtrader.core.base_connection import BaseConnection
from matchtrader.core.rate_limiter import RateLimiter


@pytest.fixture(autouse=True)
def offline_and_cleanup(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Unit tests must never contact a broker")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(RateLimiter, "wait", lambda self: None)
    yield
    for obj in list(BaseConnection._registry.values()):
        while not obj.closed:
            obj.release()


@pytest.fixture
def settings():
    return Settings(
        platform_url="https://broker.example",
        email="test@example.com",
        password="not-a-secret",
        broker_id="broker-1",
        account_id="123",
        enable_writes=True,
    )


@pytest.fixture
def auth():
    return {
        "token": "session-test",
        "tradingAccounts": [
            {
                "tradingAccountId": "123",
                "uuid": "account-uuid",
                "tradingApiToken": "trading-test",
                "tradingAccountToken": {"token": "account-test"},
                "offer": {"system": {"uuid": "system-1", "tradingApiDomain": "https://different.example"}},
            }
        ],
    }


@pytest.fixture
def api_factory(settings, auth):
    def make(handler=None, config=None):
        seen = []

        def route(request):
            seen.append(request)
            if handler:
                response = handler(request)
                if response is not None:
                    return response
            if request.url.path == "/manager/mtr-login":
                return httpx.Response(
                    200, json=auth, headers={"set-cookie": "rt=refresh-test; Path=/manager"}
                )
            return httpx.Response(200, json={"status": "OK", "orderId": "W1"})

        api = MatchTraderAPI(config or settings, transport=httpx.MockTransport(route))
        return api, seen

    return make


@pytest.fixture
def check_endpoint(api_factory):
    fixtures = json.loads((Path(__file__).parent / "fixtures/endpoints.json").read_text())

    def check(name):
        case = fixtures[name]
        expected_path = case["path"].replace("SYSTEM_UUID", "system-1")

        def handler(request):
            if request.url.path == expected_path:
                return (
                    httpx.Response(200, json=case["body"])
                    if case["body"] is not None
                    else httpx.Response(200)
                )

        api, seen = api_factory(handler)
        if name == "refresh_token":
            api.login()
        result = getattr(api, name)(**case["payload"])
        request = seen[-1]
        assert request.url.path == expected_path
        assert request.method == case["method"]
        assert request.headers["User-Agent"] == "hcamm-matchtrader/0.1.0"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Content-Type"] == "application/json"
        if case["method"] == "POST" and case["payload"]:
            assert json.loads(request.content) == case["payload"]
        elif case["method"] == "GET":
            assert dict(request.url.params) == case["payload"]
        if expected_path.startswith("/mtr-api/"):
            assert request.headers["Auth-trading-api"] == "trading-test"
        if case["collection"]:
            assert isinstance(result, list) and len(result) == 1
        elif case["body"] is None:
            assert result is None
        elif name not in ("login", "login_with_token", "register"):
            assert result.model_dump() is not None
        api.close()

    return check
