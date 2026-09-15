"""Shared, serialized HTTP session with explicit account selection and bounded refresh."""

import base64
import binascii
import json
import ssl
import time
from collections import deque
from datetime import UTC, datetime
from threading import RLock

import httpx

from .base_connection import BaseConnection
from .errors import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    ProtocolError,
    UnknownOutcomeError,
    WritesDisabledError,
)
from .rate_limiter import RateLimiter
from .reason import broker_reason, local_reason, transport_reason


class RestConnection(BaseConnection):
    def __init__(self, settings, *, _key=None, transport=None):
        super().__init__(settings, _key=_key)
        self._lock = RLock()
        verify = True
        if settings.tls_minimum_version == "TLSv1.3":
            verify = httpx.create_ssl_context(trust_env=False)
            verify.minimum_version = ssl.TLSVersion.TLSv1_3
        self._client = httpx.Client(
            verify=verify,
            timeout=settings.timeout_seconds,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "hcamm-matchtrader/0.1.0"},
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        self._limiter = RateLimiter.for_origin(settings.platform_url, settings.requests_per_minute)
        self._session_token = ""
        self._trading_token = ""
        self._account_token = ""
        self._system = settings.system_uuid
        self._expires = 0.0
        self._identity = ""
        self._refresh_times = deque()
        self.account_id = ""

    @property
    def session_expires_at(self):
        """Display the current session JWT's exp claim; not signature validation."""
        with self._lock:
            if self.closed or not self._session_token:
                return None
            try:
                parts = self._session_token.split(".")
                if len(parts) != 3:
                    return None
                claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
                expiry = claims.get("exp") if isinstance(claims, dict) else None
                if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
                    return None
                return datetime.fromtimestamp(expiry, UTC).isoformat()
            except (ValueError, TypeError, OverflowError, OSError, binascii.Error):
                return None

    def _shutdown(self):
        with self._lock:
            self._client.close()
            self._session_token = self._trading_token = self._account_token = ""

    def _send(self, method, path, *, scope="manager", body=None, params=None, write=False):
        self.ensure_open()
        from ..capture.dispatch_metrics import active, mark, trace

        mark('write_rate_wait_start' if write else 'preflight_rate_wait_start')
        self._limiter.wait()
        mark('write_rate_permit' if write else 'preflight_rate_permit')
        base = self.settings.platform_url
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if scope == "trading":
            base = self.settings.trading_url or base
            if not self._trading_token or not self._system:
                raise AuthenticationError("Login and select a trading account first")
            cookie = self._account_token if self.settings.cookie_mode == "account" else self._session_token
            if not cookie:
                raise AuthenticationError("The selected cookie mode has no token; check broker instructions")
            headers.update({"Auth-trading-api": self._trading_token, "Cookie": "co-auth=" + cookie})
            path = path.replace("SYSTEM_UUID", self._system)
        try:
            response = self._client.request(
                method, base + "/" + path.lstrip("/"), json=body, params=params, headers=headers,
                **({"extensions": {"trace": trace}} if write and active() else {})
            )
        except httpx.TransportError as exc:
            if write:
                raise UnknownOutcomeError(
                    "Mutation transport failure: outcome unknown; reconcile before retry",
                    reason=transport_reason(exc),
                ) from None
            raise APIError("Request transport failure") from None
        if write:
            mark("response_complete")
        if response.status_code == 401:
            raise AuthenticationError("Authentication expired or rejected (401)")
        if response.is_error or response.is_redirect:
            try:
                error_body = response.json()
            except ValueError:
                error_body = None
            # Never echo plaintext errors: the upstream body can contain sensitive request data.
            raise APIError(
                f"HTTP {response.status_code} from Match-Trader",
                response.status_code,
                reason=broker_reason(response.status_code, error_body),
            )
        if not response.content:
            if (
                response.status_code == 204
                and method == "POST"
                and scope == "trading"
                and path == f"mtr-api/{self._system}/pending-order/cancel"
            ):
                return {"status": "OK"}
            return None
        try:
            data = response.json()
        except ValueError as exc:
            if write:
                # The wire succeeded - a complete HTTP response came back - only parsing it
                # failed. That is our own code, not a wire failure: origin='local', never
                # 'transport'. The outcome stays honestly unconfirmed either way.
                raise UnknownOutcomeError(
                    "Mutation returned an unreadable response; reconcile before retry",
                    reason=local_reason(
                        exc, evidence="broker returned a complete response that failed JSON parsing"
                    ),
                ) from None
            raise ProtocolError("Expected a JSON response") from None
        history_full = (
            not write and method == "POST" and scope == "trading"
            and path == f"mtr-api/{self._system}/closed-positions"
            and isinstance(data, dict) and data.get("status") == "FULL"
            and isinstance(data.get("operations"), list)
        )
        if isinstance(data, dict) and isinstance(data.get("status"), str) and data["status"] != "OK" and not history_full:
            raise APIError(
                "Operation did not report OK; inspect broker state before continuing",
                reason=broker_reason(response.status_code, data),
            )
        return data

    def _adopt(self, data, identity=""):
        if not isinstance(data, dict) or not data.get("token"):
            raise ProtocolError("Login response has no session token")
        accounts = data.get("tradingAccounts") or data.get("accounts") or []
        selected = data.get("selectedTradingAccount") or data.get("selectedAccount")
        if selected and not accounts:
            accounts = [selected]
        if self.settings.account_id:
            matches = [a for a in accounts if str(a.get("tradingAccountId")) == self.settings.account_id]
            if len(matches) != 1:
                raise AuthenticationError("Configured account ID was not uniquely present in login")
            account = matches[0]
        elif len(accounts) == 1:
            account = accounts[0]
        else:
            raise AuthenticationError("Set the broker's ACCOUNT_ID: login did not return exactly one account")
        system = self.settings.system_uuid or account.get("offer", {}).get("system", {}).get("uuid", "")
        if not system or not all(c.isalnum() or c in "-_" for c in system):
            raise ProtocolError("Login returned an invalid system identifier")
        if not account.get("tradingApiToken"):
            raise ProtocolError("Selected account has no trading API token")
        self._session_token = data["token"]
        self._trading_token = account["tradingApiToken"]
        self._account_token = (account.get("tradingAccountToken") or {}).get("token", "")
        self._system = system
        self.account_id = str(account["tradingAccountId"])
        self._identity = identity
        self._expires = time.monotonic() + 900

    def discover_accounts(self):
        """Authenticate a temporary, unselected owner without adopting an account."""
        with self._lock:
            self.ensure_open()
            if self.settings.account_id or self._session_token:
                raise ConfigurationError('Account discovery requires an unselected session')
            return self._login(discover_only=True)

    def adopt_login(self, data):
        with self._lock:
            self.ensure_open()
            if not self.settings.account_id:
                raise ConfigurationError('Select an account before adopting a login')
            self._adopt(data, self.settings.email)

    def _login(self, body=None, one_time=False, discover_only=False):
        if body is None:
            if not self.settings.email or not self.settings.password.get_secret_value():
                raise AuthenticationError("Set the broker's EMAIL and PASSWORD in your local .env")
            broker = self.settings.broker_id
            if not broker:
                platform = self._send("GET", "/manager/platform-details")
                if not isinstance(platform, dict) or not platform.get("partnerId"):
                    raise ProtocolError("Platform details has no partnerId")
                broker = platform["partnerId"]
            body = {
                "email": self.settings.email,
                "password": self.settings.password.get_secret_value(),
                "brokerId": broker,
            }
        identity = body.get("email", self.settings.email)
        if self._session_token and (one_time or self._identity != identity):
            raise ConfigurationError("Close the active session before logging in as another identity")
        path = "/manager/login/co/with-token" if one_time else "/manager/mtr-login"
        data = self._send("POST", path, body=body)
        if discover_only:
            return data
        # Clear old state if login succeeds but account selection fails.
        self._session_token = self._trading_token = self._account_token = ""
        self._adopt(data, identity)
        return data

    def renewal_due(self, margin_seconds=120):
        """True when a session exists and its token has two minutes or less left. The token's own
        expiry is the authority: renew when the time remaining is within the margin, whatever the
        internal 15-minute timer says. Only when the token carries no readable expiry does the
        monotonic timer stand in for it. Cheap: no network."""
        with self._lock:
            if self.closed or not self._session_token:
                return False
            expiry = self.session_expires_at
            if expiry:
                try:
                    remaining = (datetime.fromisoformat(expiry) - datetime.now(UTC)).total_seconds()
                except ValueError:
                    return time.monotonic() >= self._expires
                return remaining <= margin_seconds
            return time.monotonic() >= self._expires

    def renewal_delay(self, margin_seconds=120):
        """Seconds from now until renewal becomes due, so a scheduler can sleep exactly that long
        instead of polling. 0 when already due, None when there is no session to keep alive. Cheap:
        no network. The token's own expiry is the authority; the monotonic timer stands in only when
        the token carries no readable expiry."""
        with self._lock:
            if self.closed or not self._session_token:
                return None
            expiry = self.session_expires_at
            if expiry:
                try:
                    remaining = (datetime.fromisoformat(expiry) - datetime.now(UTC)).total_seconds()
                except ValueError:
                    return max(0.0, self._expires - time.monotonic())
                return max(0.0, remaining - margin_seconds)
            return max(0.0, self._expires - time.monotonic())

    def renew_if_due(self, margin_seconds=120):
        """Renew on the timer, not on the next request. Returns True when a renewal ran."""
        with self._lock:
            if not self.renewal_due(margin_seconds):
                return False
            self._renew()
            return True

    def _reserve_renewal(self):
        now = time.monotonic()
        while self._refresh_times and self._refresh_times[0] <= now - 3600:
            self._refresh_times.popleft()
        if len(self._refresh_times) >= 4:
            raise AuthenticationError("Refresh limit reached (four attempts/hour); check credentials or wait")
        self._refresh_times.append(now)

    def _renew(self):
        """Reauthenticate or refresh once, according to the broker configuration."""
        if self.settings.session_renewal == "refresh":
            try:
                return self._refresh()
            except (APIError, AuthenticationError, ProtocolError):
                # The broker's refresh endpoint is unavailable or rejected the token. Keep the
                # active session alive with a full re-login instead of letting it expire, when the
                # active identity's own credentials back this session (as a broker profile's do).
                if self._identity and self._identity == self.settings.email and self.settings.account_id:
                    return self._login()
                raise
        if not self._session_token:
            raise AuthenticationError("Login before renewing the session")
        if self._identity != self.settings.email:
            raise ConfigurationError("Automatic login requires the active identity's configured credentials")
        self._reserve_renewal()
        try:
            return self._login()
        except Exception:
            self._expires = 0
            raise

    def _refresh(self):
        if not self._session_token:
            raise AuthenticationError("Login before refreshing the session")
        self._reserve_renewal()
        try:
            data = self._send("POST", "/manager/refresh-token")
            if isinstance(data, dict) and data.get("token"):
                if any(
                    key in data
                    for key in ("accounts", "tradingAccounts", "selectedAccount", "selectedTradingAccount")
                ):
                    self._adopt(data, self._identity)
                else:
                    self._session_token = data["token"]
            else:
                # Read only the cookie for the configured origin, not another API host.
                probe = self._client.build_request(
                    "GET", self.settings.platform_url + "/manager/platform-details"
                )
                from http.cookies import SimpleCookie

                cookie = SimpleCookie(probe.headers.get("Cookie", ""))
                if "co-auth" in cookie:
                    self._session_token = cookie["co-auth"].value
            self._expires = time.monotonic() + 900
            return data
        except Exception:
            self._expires = 0
            raise

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
        with self._lock:
            self.ensure_open()
            if write and not self.settings.enable_writes:
                raise WritesDisabledError("Enable writes for this broker in your local .env to use mutation endpoints")
            if action == "login":
                return self._login(body)
            if action == "one_time_login":
                return self._login(body, one_time=True)
            if action == "refresh":
                return self._refresh()
            refreshed = False
            if scope == "trading":
                if not self._session_token:
                    self._login()
                elif time.monotonic() >= self._expires:
                    self._renew()
                    refreshed = True
            try:
                return self._send(method, path, scope=scope, body=body, params=params, write=write)
            except AuthenticationError:
                if scope != "trading" or not safe_read or refreshed:
                    raise
                self._renew()
                return self._send(method, path, scope=scope, body=body, params=params, write=write)
