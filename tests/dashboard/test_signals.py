import _socket
import json
import socket
from concurrent.futures import ThreadPoolExecutor

import pytest
from websockets.sync.client import connect

from matchtrader.dashboard.signals import SignalHub, SignalServer


def test_raw_json_text_and_unknown_shapes_are_preserved_and_persisted(tmp_path):
    path = tmp_path / "signals.sqlite3"
    hub = SignalHub(path)
    raw = ' {"source":"R01", "event_type":"ENTRY", "symbol":"XAUUSD", "custom":{"a":1}} '
    try:
        queue = hub.subscribe()
        assert queue.get()["type"] == "snapshot"
        ack = hub.publish(raw)
        event = queue.get()["event"]
        assert ack["parsed"] and event["source"] == "R01" and event["kind"] == "ENTRY"
        assert event["raw"] == raw and event["payload"]["custom"] == {"a": 1}
        assert not hub.publish("plain strategy signal", "StrategyManager")["parsed"]
        hub.publish("[1,2,3]")
        hub.publish('{"value":NaN}')
        assert hub.recent()[-1]["parsed"] is False
        with pytest.raises(ValueError):
            hub.publish("x" * 65537)
        hub.unsubscribe(queue)
    finally:
        hub.close()
    hub = SignalHub(path)
    assert len(hub.recent()) == 4 and hub.recent()[0]["raw"] == raw
    hub.close()


def test_concurrent_publish_order_and_slow_subscriber_resynchronization(tmp_path):
    hub = SignalHub(tmp_path / "signals.sqlite3")
    try:
        queue = hub.subscribe()
        queue.get()
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda n: hub.publish(str(n)), range(40)))
        ids = [queue.get()["event"]["id"] for _ in range(40)]
        assert ids == sorted(ids)
        for n in range(300):
            hub.publish(str(n))
        assert queue.get()["type"] == "snapshot"
        assert len(hub.recent()) == 200
    finally:
        hub.close()


def test_real_websocket_publish_ack_and_live_subscribe_without_token(tmp_path, monkeypatch):
    def local_connect(sock, address):
        assert address[0] in {"127.0.0.1", "::1"}
        return _socket.socket.connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_connect)
    hub = SignalHub(tmp_path / "signals.sqlite3")
    try:
        with SignalServer(hub, port=0) as server:
            base = f"ws://127.0.0.1:{server.port}"
            with (
                connect(base + "/events", proxy=None) as viewer,
                connect(base + "/signals?source=R01", proxy=None) as sender,
            ):
                assert json.loads(viewer.recv(timeout=2))["type"] == "snapshot"
                raw = '{"event_id":"unit-signal","kind":"ENTRY","price":4340}'
                sender.send(raw)
                ack = json.loads(sender.recv(timeout=2))
                assert ack["status"] == "received" and ack["event_id"] == "unit-signal"
                received = json.loads(viewer.recv(timeout=2))["event"]
                assert received["raw"] == raw and received["source"] == "R01"
                sender.send("")
                assert json.loads(sender.recv(timeout=2))["status"] == "rejected"
            with connect(base + "/events", proxy=None) as reopened:
                assert len(json.loads(reopened.recv(timeout=2))["events"]) == 1
    finally:
        hub.close()
