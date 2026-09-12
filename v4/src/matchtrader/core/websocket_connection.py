"""Protocol-neutral optional socket; broker-specific subscription frames are explicit."""

import json
from threading import Lock

from websockets.sync.client import connect

from .base_connection import BaseConnection
from .errors import ConfigurationError, ProtocolError


class WebSocketConnection(BaseConnection):
    def __init__(self, settings, *, _key=None, connector=connect):
        super().__init__(settings, _key=_key)
        if not settings.ws_url:
            raise ConfigurationError("Set the broker-confirmed WS_URL and protocol settings first")
        self._socket = connector(
            settings.ws_url,
            additional_headers=json.loads(settings.ws_headers_json.get_secret_value()),
            subprotocols=[settings.ws_subprotocol] if settings.ws_subprotocol else None,
            open_timeout=settings.timeout_seconds,
            close_timeout=settings.timeout_seconds,
            ping_interval=settings.ws_ping_interval,
            ping_timeout=settings.ws_ping_interval,
            max_size=settings.ws_max_size,
            max_queue=16,
            proxy=None,
        )
        self._receive_lock = Lock()

    def send(self, message: str | bytes | dict):
        self.ensure_open()
        self._socket.send(json.dumps(message) if isinstance(message, dict) else message)

    def receive(self, timeout: float | None = None):
        self.ensure_open()
        if not self._receive_lock.acquire(blocking=False):
            raise ProtocolError("Only one consumer can receive from the shared WebSocket at a time")
        try:
            return self._socket.recv(timeout=timeout)
        finally:
            self._receive_lock.release()

    def _shutdown(self):
        self._socket.close()
