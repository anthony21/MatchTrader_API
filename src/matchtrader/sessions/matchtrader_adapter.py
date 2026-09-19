"""Request-scoped SDK views over a broker-owned async transport and token cache."""

import base64
import copy
import json
import math
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from http.cookies import SimpleCookie
from threading import RLock
from typing import ClassVar
from urllib.parse import urlsplit

from ..api import MatchTraderAPI
from ..core.errors import AuthenticationError, ProtocolError, WritesDisabledError
from ..core.rest_connection import RestConnection
from ..models.authentication import Authentication
from .async_transport import AsyncRequestPool, PoolLease, TransportSettings
from .session_manager import SessionData


class ManagedConnection(RestConnection):
    """Application adapter hook: authentication belongs exclusively to SessionManager."""

    _registry: ClassVar[dict] = {}

    def request(
        self,
        method,
        path,
        *,
        body=None,
        params=None,
        scope="trading",
        write=False,
        safe_read=False,
        action="",
    ):
        if action:
            raise AuthenticationError("Use the broker session manager for authentication")
        if write and not self.settings.enable_writes:
            raise WritesDisabledError("Broker mutations are disabled")
        return self._send(method, path, body=body, params=params, scope=scope, write=write)


class ManagedAPI(MatchTraderAPI):
    def __init__(self, settings, connection):
        self.settings = settings
        self.connection = connection
        self.closed = False
        self._stream = None
        self._lifecycle_lock = RLock()


@dataclass(repr=False)
class TokenCache:
    auth: dict = field(repr=False)
    cookies: object = field(repr=False)


def _cookies(source):
    jar = CookieJar()
    for cookie in source:
        jar.set_cookie(copy.copy(cookie))
    return jar


def _expiry(token):
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError
        claim = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))["exp"]
        if isinstance(claim, bool) or not isinstance(claim, (int, float)) or not math.isfinite(claim):
            raise ValueError
        return float(claim)
    except (ValueError, TypeError, KeyError, IndexError):
        raise ProtocolError("Broker token needs a numeric JWT expiry for scheduled renewal") from None


class MatchTraderAdapter:
    def __init__(
        self,
        settings,
        *,
        transport_factory=None,
        require_demo=False,
        transport_settings=None,
        async_transport_factory=None,
    ):
        self.settings = settings
        self.require_demo = require_demo
        self.identity = ("matchtrader", settings.platform_url.lower(), settings.broker_id)
        self.transport_factory = transport_factory
        self.transport_settings = transport_settings or TransportSettings()
        self._async_transport_factory = async_transport_factory
        self._pool = None
        self._pool_lock = RLock()

    def _get_pool(self):
        with self._pool_lock:
            if self._pool is None:
                self._pool = AsyncRequestPool(
                    self.transport_settings, transport_factory=self._async_transport_factory
                )
            return self._pool

    def close(self):
        with self._pool_lock:
            pool, self._pool = self._pool, None
        if pool:
            pool.close()

    def transport_status(self):
        with self._pool_lock:
            return (
                self._pool.status()
                if self._pool
                else {**self.transport_settings.model_dump(), "io": "async", "last_failure": None}
            )

    def _connection(self, account_id=""):
        settings = self.settings.model_copy(update={"account_id": account_id, "system_uuid": ""})
        options = {
            "transport": self.transport_factory() if self.transport_factory else PoolLease(self._get_pool())
        }
        # This adapter intentionally opts out of the SDK's leased client registry.
        # Concurrent requests use isolated SDK views over one async broker pool.
        return ManagedConnection(settings, _key=ManagedConnection._creation_key, **options)

    def _data(self, connection, auth):
        if not isinstance(auth, dict) or not isinstance(auth.get("token"), str):
            raise ProtocolError("Broker supplied no session token")
        accounts = auth.get("tradingAccounts") or auth.get("accounts") or []
        if not accounts:
            selected = auth.get("selectedTradingAccount") or auth.get("selectedAccount")
            accounts = [selected] if selected else []
        ids = tuple(str(a["tradingAccountId"]) for a in accounts)
        for account_id in ids:
            connection.settings = connection.settings.model_copy(update={"account_id": account_id})
            connection._adopt(auth, self.settings.email)
        return SessionData(
            _expiry(auth["token"]),
            ids,
            TokenCache(copy.deepcopy(auth), _cookies(connection._client.cookies.jar)),
        )

    def login(self):
        connection = self._connection()
        try:
            broker = self.settings.broker_id
            if not broker:
                details = connection._send("GET", "/manager/platform-details")
                broker = details.get("partnerId") if isinstance(details, dict) else None
                if not broker:
                    raise ProtocolError("Platform details has no partnerId")
            auth = connection._send(
                "POST",
                "/manager/mtr-login",
                body={
                    "email": self.settings.email,
                    "password": self.settings.password.get_secret_value(),
                    "brokerId": broker,
                },
            )
            return self._data(connection, auth)
        finally:
            connection.release()

    def refresh(self, previous):
        if self.settings.session_renewal == "login":
            return self.login()
        connection = self._connection()
        try:
            connection._client.cookies = _cookies(previous.payload.cookies)
            # Some brokers return only the JSON token, without a Set-Cookie header.
            probe = connection._client.build_request(
                "POST", self.settings.platform_url + "/manager/refresh-token"
            )
            if "co-auth" not in SimpleCookie(probe.headers.get("Cookie", "")):
                connection._client.cookies.set(
                    "co-auth",
                    previous.payload.auth["token"],
                    domain=urlsplit(self.settings.platform_url).hostname,
                    path="/",
                )
            response = connection._send("POST", "/manager/refresh-token")
            auth = copy.deepcopy(previous.payload.auth)
            if isinstance(response, dict) and response.get("token"):
                auth["token"] = response["token"]
            else:
                probe = connection._client.build_request(
                    "GET", self.settings.platform_url + "/manager/platform-details"
                )
                cookie = SimpleCookie(probe.headers.get("Cookie", ""))
                if "co-auth" not in cookie:
                    raise ProtocolError("Refresh returned no session token")
                auth["token"] = cookie["co-auth"].value
            account_fields = ("tradingAccounts", "accounts", "selectedTradingAccount", "selectedAccount")
            if isinstance(response, dict) and any(k in response for k in account_fields):
                for key in account_fields:
                    auth.pop(key, None)
                auth.update({key: response[key] for key in account_fields if key in response})
            # Keep manager cookie synchronized with token-only responses.
            for cookie in list(connection._client.cookies.jar):
                if cookie.name == "co-auth":
                    connection._client.cookies.delete(cookie.name, cookie.domain, cookie.path)
            connection._client.cookies.set(
                "co-auth", auth["token"], domain=urlsplit(self.settings.platform_url).hostname, path="/"
            )
            return self._data(connection, auth)
        except AuthenticationError:
            # A revoked/expired refresh credential needs a new broker login.
            # This runs under the same session owner; it cannot create a second session.
            connection.release()
            return self.login()
        finally:
            connection.release()

    def execute(self, session, account_id, operation, *args, **kwargs):
        if operation not in ACCOUNT_OPERATIONS:
            raise ValueError("Operation is not an account request")
        if self.require_demo and operation in MUTATIONS:
            auth = Authentication.model_validate(session.payload.auth)
            accounts = auth.tradingAccounts or auth.accounts
            if not accounts:
                accounts = [a for a in (auth.selectedTradingAccount, auth.selectedAccount) if a]
            if not any(a.tradingAccountId == account_id and a.offer.get("demo") is True for a in accounts):
                raise WritesDisabledError("The route destination is no longer verified as demo")
        connection = self._connection(account_id)
        try:
            connection._adopt(session.payload.auth, self.settings.email)
            with ManagedAPI(connection.settings, connection) as api:
                return getattr(api, operation)(*args, **kwargs)
        finally:
            if not connection.closed:
                connection.release()


# Authentication and raw connections cannot escape through a consumer handle.
ACCOUNT_OPERATIONS = frozenset(
    {
        "balance",
        "active_orders",
        "open_positions",
        "closed_positions",
        "instruments",
        "candles",
        "partial_close",
        "quotes",
        "open_position",
        "close_position",
        "edit_position",
        "create_pending_order",
        "edit_pending_order",
        "cancel_pending_order",
    }
)

MUTATIONS = frozenset(
    {
        "open_position",
        "close_position",
        "edit_position",
        "partial_close",
        "create_pending_order",
        "edit_pending_order",
        "cancel_pending_order",
    }
)


class AccountSession:
    """A lightweight account reference; does not own authentication or an HTTP client."""

    def __init__(self, manager, broker, settings):
        self.manager, self.broker, self.settings = manager, broker, settings
        self.account_id = settings.account_id
        self.closed = False

    @property
    def connection(self):
        return self

    @property
    def session_expires_at(self):
        return self.manager.status(self.broker)["expires_at"]

    def login(self):
        if self.closed:
            raise RuntimeError("Account handle is closed")
        data = self.manager.connect(self.broker)
        if self.account_id not in data.accounts:
            raise AuthenticationError("Configured account is absent from this broker")
        return Authentication.model_validate(data.payload.auth)

    def refresh(self):
        data = self.manager.refresh(self.broker)
        return Authentication.model_validate(data.payload.auth)

    def close(self):
        self.closed = True

    async def aexecute(self, operation, *args, **kwargs):
        if self.closed:
            raise RuntimeError("Account handle is closed")
        if operation not in ACCOUNT_OPERATIONS:
            raise ValueError("Operation is not an account request")
        return await self.manager.aexecute(self.broker, self.account_id, operation, *args, **kwargs)

    def __getattr__(self, operation):
        if operation not in ACCOUNT_OPERATIONS:
            raise AttributeError(operation)

        def call(*args, **kwargs):
            if self.closed:
                raise RuntimeError("Account handle is closed")
            return self.manager.execute(self.broker, self.account_id, operation, *args, **kwargs)

        return call
