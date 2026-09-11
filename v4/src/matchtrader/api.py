"""The single public facade; endpoint implementation lives in separate modules."""

from threading import RLock

from .core.errors import ConfigurationError, ConnectionClosedError
from .core.rest_connection import RestConnection
from .core.settings import Settings
from .core.websocket_connection import WebSocketConnection
from .endpoints.active_orders import GetActiveOrders
from .endpoints.balance import GetBalance
from .endpoints.cancel_pending_order import CancelPendingOrder
from .endpoints.candles import GetCandles
from .endpoints.close_position import ClosePosition
from .endpoints.closed_positions import GetClosedPositions
from .endpoints.create_pending_order import CreatePendingOrder
from .endpoints.edit_pending_order import EditPendingOrder
from .endpoints.edit_position import EditPosition
from .endpoints.instruments import GetInstruments
from .endpoints.login import Login
from .endpoints.login_with_token import LoginWithToken
from .endpoints.open_position import OpenPosition
from .endpoints.open_positions import GetOpenPositions
from .endpoints.partial_close import PartialClose
from .endpoints.platform_details import GetPlatformDetails
from .endpoints.quotes import GetQuotes
from .endpoints.refresh_token import RefreshToken
from .endpoints.register import Register


class MatchTraderAPI:
    def __init__(self, settings: Settings | None = None, *, transport=None):
        self.settings = settings if settings is not None else Settings.from_env()
        dependencies = {} if transport is None else {"transport": transport}
        self.connection = RestConnection.acquire(self.settings, **dependencies)
        self.closed = False
        self._stream = None
        self._lifecycle_lock = RLock()

    def __enter__(self):
        if self.closed:
            raise ConnectionClosedError("API owner is closed")
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        with self._lifecycle_lock:
            if self.closed:
                return
            self.closed = True
            try:
                if self._stream is not None:
                    self._stream.release()
            finally:
                self.connection.release()

    def websocket(self):
        with self._lifecycle_lock:
            if self.closed:
                raise ConnectionClosedError("API owner is closed")
            if self._stream is None:
                self._stream = WebSocketConnection.acquire(self.settings)
            return self._stream

    def for_account(self, account_id: str, *, transport=None, **overrides):
        """Return an independently owned account facade; use it in its own with block.

        Credentials default to this login. Account-specific system and streaming
        settings are cleared unless explicitly supplied for the new account.
        """
        with self._lifecycle_lock:
            if self.closed:
                raise ConnectionClosedError("API owner is closed")
            if not isinstance(account_id, str) or not account_id.strip():
                raise ConfigurationError("An explicit nonempty trading account ID is required")
            values = self.settings.model_dump()
            if account_id != self.settings.account_id:
                values.update(system_uuid="", ws_url="", ws_headers_json="{}", ws_subprotocol="")
            values.update(overrides)
            values["account_id"] = account_id.strip()
            return MatchTraderAPI(Settings.model_validate(values), transport=transport)

    def account_dataframe(self, records, **options):
        """Normalize records and label every row with its broker and account."""
        if self.closed:
            raise ConnectionClosedError("API owner is closed")
        account_id = self.connection.account_id or self.settings.account_id
        if not account_id:
            raise ConfigurationError("Select or log in to an account before labeling data")
        frame = self.dataframe(records, **options)
        if {"mtr_account_id", "mtr_platform_url"} & set(frame.columns):
            raise ConfigurationError("Account metadata columns already exist; do not overwrite provenance")
        frame["mtr_account_id"] = account_id
        frame["mtr_platform_url"] = self.settings.platform_url
        return frame

    def platform_details(self, payload=None, **kwargs):
        """See endpoints/platform_details.py and its request model."""
        return GetPlatformDetails(self).execute(payload, **kwargs)

    def register(self, payload=None, **kwargs):
        """See endpoints/register.py and its request model."""
        return Register(self).execute(payload, **kwargs)

    def discover_accounts(self):
        """Read the authenticated account list before selecting a trading session."""
        from .models.authentication import Authentication
        return Authentication.model_validate(self.connection.discover_accounts())

    def use_login(self, authentication):
        """Adopt a backend-held login into this explicitly selected account owner."""
        accounts = authentication.tradingAccounts or authentication.accounts
        if not accounts:
            selected = authentication.selectedTradingAccount or authentication.selectedAccount
            accounts = [selected] if selected else []
        data = {'token': authentication.token.get_secret_value(), 'accounts': [
            {**a.model_dump(mode='json'), 'tradingApiToken': a.tradingApiToken.get_secret_value(),
             'tradingAccountToken': a.tradingAccountToken} for a in accounts]}
        self.connection.adopt_login(data)
        return authentication

    def login(self, payload=None, **kwargs):
        """See endpoints/login.py and its request model."""
        if payload is None and not kwargs:
            from .models.authentication import Authentication

            if self.closed:
                raise ConnectionClosedError("API owner is closed")
            return Authentication.model_validate(
                self.connection.request("POST", "/manager/mtr-login", scope="manager", action="login")
            )
        return Login(self).execute(payload, **kwargs)

    @staticmethod
    def dataframe(records, **options):
        from .analysis.frames import to_frame

        return to_frame(records, **options)

    @staticmethod
    def analyze_closed_operations(records, **options):
        from .analysis.performance import summarize_closed_operations

        return summarize_closed_operations(records, **options)

    def refresh_token(self, payload=None, **kwargs):
        """See endpoints/refresh_token.py and its request model."""
        return RefreshToken(self).execute(payload, **kwargs)

    def login_with_token(self, payload=None, **kwargs):
        """See endpoints/login_with_token.py and its request model."""
        return LoginWithToken(self).execute(payload, **kwargs)

    def quotes(self, payload=None, **kwargs):
        """See endpoints/quotes.py and its request model."""
        return GetQuotes(self).execute(payload, **kwargs)

    def balance(self, payload=None, **kwargs):
        """See endpoints/balance.py and its request model."""
        return GetBalance(self).execute(payload, **kwargs)

    def instruments(self, payload=None, **kwargs):
        """See endpoints/instruments.py and its request model."""
        return GetInstruments(self).execute(payload, **kwargs)

    def candles(self, payload=None, **kwargs):
        """See endpoints/candles.py and its request model."""
        return GetCandles(self).execute(payload, **kwargs)

    def open_positions(self, payload=None, **kwargs):
        """See endpoints/open_positions.py and its request model."""
        return GetOpenPositions(self).execute(payload, **kwargs)

    def open_position(self, payload=None, **kwargs):
        """See endpoints/open_position.py and its request model."""
        return OpenPosition(self).execute(payload, **kwargs)

    def edit_position(self, payload=None, **kwargs):
        """See endpoints/edit_position.py and its request model."""
        return EditPosition(self).execute(payload, **kwargs)

    def partial_close(self, payload=None, **kwargs):
        """See endpoints/partial_close.py and its request model."""
        return PartialClose(self).execute(payload, **kwargs)

    def close_position(self, payload=None, **kwargs):
        """See endpoints/close_position.py and its request model."""
        return ClosePosition(self).execute(payload, **kwargs)

    def closed_positions(self, payload=None, **kwargs):
        """See endpoints/closed_positions.py and its request model."""
        return GetClosedPositions(self).execute(payload, **kwargs)

    def active_orders(self, payload=None, **kwargs):
        """See endpoints/active_orders.py and its request model."""
        return GetActiveOrders(self).execute(payload, **kwargs)

    def create_pending_order(self, payload=None, **kwargs):
        """See endpoints/create_pending_order.py and its request model."""
        return CreatePendingOrder(self).execute(payload, **kwargs)

    def edit_pending_order(self, payload=None, **kwargs):
        """See endpoints/edit_pending_order.py and its request model."""
        return EditPendingOrder(self).execute(payload, **kwargs)

    def cancel_pending_order(self, payload=None, **kwargs):
        """See endpoints/cancel_pending_order.py and its request model."""
        return CancelPendingOrder(self).execute(payload, **kwargs)
