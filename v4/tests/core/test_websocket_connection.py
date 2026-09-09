from unittest.mock import Mock

import pytest

from matchtrader.core.errors import ConfigurationError, ConnectionClosedError, ProtocolError
from matchtrader.core.websocket_connection import WebSocketConnection


def test_optional_socket_needs_explicit_url(settings):
    with pytest.raises(ConfigurationError):
        WebSocketConnection.acquire(settings)


def test_shared_socket_bounded_buffers_and_cleanup(settings):
    connector = Mock()
    socket = connector.return_value
    socket.recv.return_value = "quote-frame"
    config = settings.model_copy(update={"ws_url": "wss://stream.example/socket"})
    first = WebSocketConnection.acquire(config, connector=connector)
    second = WebSocketConnection.acquire(config)
    assert first is second
    first.send({"subscribe": "broker-specific"})
    assert socket.send.call_args.args[0] == '{"subscribe": "broker-specific"}'
    assert first.receive(timeout=1) == "quote-frame"
    assert connector.call_args.kwargs["max_queue"] == 16
    assert connector.call_args.kwargs["ping_interval"] == 20
    assert connector.call_args.kwargs["proxy"] is None
    first._receive_lock.acquire()
    with pytest.raises(ProtocolError):
        first.receive(timeout=1)
    first._receive_lock.release()
    first.release()
    socket.close.assert_not_called()
    second.release()
    socket.close.assert_called_once()
    with pytest.raises(ConnectionClosedError):
        first.send("closed")


def test_account_streams_are_independent(settings):
    first_connector, second_connector = Mock(), Mock()
    first_config = settings.model_copy(update={"ws_url": "wss://stream.example/socket"})
    second_config = first_config.model_copy(update={"account_id": "456"})
    first = WebSocketConnection.acquire(first_config, connector=first_connector)
    second = WebSocketConnection.acquire(second_config, connector=second_connector)
    assert first is not second
    first.release()
    first_connector.return_value.close.assert_called_once()
    second_connector.return_value.close.assert_not_called()
    second.send("still-open")
    second_connector.return_value.send.assert_called_once_with("still-open")
