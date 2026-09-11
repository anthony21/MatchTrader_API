import json
import socket
from contextlib import contextmanager
from decimal import Decimal
from threading import Event
from uuid import uuid4

import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from matchtrader.capture.ws_ingress import CaptureWebSocketServer
from matchtrader.dashboard.controller import DashboardController

TOKEN = 'test-capture-token-32-characters-long'


@pytest.fixture
def receiver(settings, tmp_path, monkeypatch):
    # Windows asyncio builds its wakeup pipe with loopback sockets. Keep all
    # broker connections blocked while allowing this explicit private socket pair.
    def private_pair(*args, **kwargs):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            sender = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            assert sender.connect_ex(listener.getsockname()) == 0
            receiver, _ = listener.accept()
            return receiver, sender
    monkeypatch.setattr(socket, 'socketpair', private_pair)
    controller = DashboardController(settings, tmp_path)
    server = CaptureWebSocketServer(controller, TOKEN, port=0, max_inflight=2).start()
    controller.capture_websocket = server
    yield server
    if not controller.native_store.closed:
        controller.close()


@contextmanager
def client(server, *, token=TOKEN, path='/capture/ws', origin=None, protocols=None):
    address = ('127.0.0.1', server.port)
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(3)
    assert connection.connect_ex(address) == 0  # Explicit test loopback; global broker network stays blocked.
    try:
        with connect(f'ws://127.0.0.1:{server.port}{path}', sock=connection,
                     additional_headers={'Authorization': 'Bearer ' + token},
                     subprotocols=['hcamm.capture.v1'] if protocols is None else protocols,
                     origin=origin, proxy=None, open_timeout=3, close_timeout=1) as ws:
            yield ws
    finally:
        connection.close()


def greet(ws, machine='qt'):
    ws.send(json.dumps({'type': 'hello', 'transport_version': '1.0.0', 'event_schema_version': '1.1.0',
                        'machine': machine, 'sender_instance_id': str(uuid4())}))
    return json.loads(ws.recv(timeout=3))


def test_raw_monitor_includes_rejected_messages_without_journaling(receiver):
    with client(receiver) as ws:
        assert greet(ws)['type'] == 'ready'
        ws.send('{invalid json')
        assert json.loads(ws.recv(timeout=3))['type'] == 'nack'
    rows = receiver.controller.native_store.raw_log.stream_snapshot()['events']
    assert any(row['raw'] == '{invalid json' for row in rows)
    assert any('invalid_json' in row['raw'] or 'invalid_event' in row['raw'] for row in rows)
    assert receiver.controller.native_store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0


def envelope(event, **updates):
    return json.dumps({'type': 'event', 'transport_version': '1.0.0',
                       'event': event.model_copy(update={'schema_version': '1.1.0', **updates}).model_dump(mode='json')})


@pytest.mark.parametrize(('options','status'), [({'token': 'wrong'},401), ({'path':'/wrong'},404),
    ({'origin':'https://attacker.example'},403), ({'protocols':['other']},400)])
def test_upgrade_requires_native_authentication(receiver, options, status):
    with pytest.raises(InvalidStatus) as failure, client(receiver, **options):
        pass
    assert failure.value.response.status_code == status


def test_stopped_capture_ack_replay_http_dedup_and_identity_conflict(receiver, event):
    with client(receiver) as ws:
        assert greet(ws)['capture_running'] is False
        ws.send(envelope(event))
        assert json.loads(ws.recv(timeout=3))['code'] == 'capture_stopped'
        receiver.controller.start('123')
        message = envelope(event)
        ws.send([message[:40], message[40:]])  # Fragmentation is handled before validation.
        result = json.loads(ws.recv(timeout=3))
        assert result['type'] == 'ack' and result['durable']
        assert result['result']['status'] == 'held' and not result['duplicate']
        ws.send(message)
        assert json.loads(ws.recv(timeout=3))['duplicate']
        # Existing HTTP ingress uses this exact controller entry point.
        replay = receiver.controller.receive_native(json.loads(message)['event'])
        assert replay['duplicate'] and replay['trade_id'] == result['result']['trade_id']
        ws.send(envelope(event, quantity=Decimal('2')))
        assert json.loads(ws.recv(timeout=3))['code'] == 'identity_conflict'
        ws.send(envelope(event, event_id='other', machine='not-qt'))
        assert json.loads(ws.recv(timeout=3))['code'] == 'machine_mismatch'
        assert receiver.status()['metrics']['writes_measured'] == 0


def test_machine_exclusive_and_binary_oversize_rejected(receiver):
    with client(receiver) as first:
        assert greet(first)['type'] == 'ready'
        with client(receiver) as second:
            assert greet(second)['code'] == 'sender_busy'
        first.send(b'not text')
        with pytest.raises(ConnectionClosed):
            first.recv(timeout=3)
    with client(receiver) as ws:
        assert greet(ws, 'different')['type'] == 'ready'
        ws.send('a' * 32769)
        with pytest.raises(ConnectionClosed):
            ws.recv(timeout=3)


def test_bounded_inflight_and_stop_recheck_while_broker_worker_blocked(receiver, event, monkeypatch):
    controller = receiver.controller
    controller.start('123')
    entered, release = Event(), Event()
    original = controller.receive_native
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(controller, 'receive_native', delayed)
    try:
        with client(receiver) as ws:
            greet(ws)
            ws.send(envelope(event))
            assert entered.wait(2)
            ws.send(envelope(event, event_id='two'))
            ws.send(envelope(event, event_id='three'))
            assert json.loads(ws.recv(timeout=3))['code'] == 'busy'
            assert ws.ping().wait(1)  # Blocking broker work doesn't block the WebSocket loop.
            controller.stop()
            controller.start('123')  # New generation cannot run queued work from the previous session.
            release.set()
            assert json.loads(ws.recv(timeout=3))['code'] == 'capture_stopped'
            assert json.loads(ws.recv(timeout=3))['code'] == 'capture_stopped'
            assert controller.native_store.feed() == []
    finally:
        release.set()


def test_lost_ack_replay_never_repeats_a_write(receiver, event, route, broker):
    controller = receiver.controller
    controller.start('123')
    route = route.model_copy(update={'destination_account': '123'})
    controller.native.route = route
    controller.native.armed = controller.native.demo_verified = True
    broker.close = lambda: None
    controller.api = broker
    with client(receiver) as ws:
        greet(ws)
        ws.send(envelope(event))
        ack = json.loads(ws.recv(timeout=3))
        assert ack['result']['status'] == 'accepted'
        assert len(broker.calls) == 1
        # The sender can replay even when its own durable ACK log was lost.
        ws.send(envelope(event))
        replay = json.loads(ws.recv(timeout=3))
        assert replay['duplicate'] and replay['result']['broker_order_id'] == 'aqua1'
        assert len(broker.calls) == 1
        # Observational fills cannot trigger another create.
        ws.send(envelope(event, event_id='fill', kind='FILL', action='OBSERVE', execution_id='fill1', fill_effect='OPEN'))
        assert json.loads(ws.recv(timeout=3))['result']['status'] == 'captured'
        assert len(broker.calls) == 1


def test_socket_disconnect_during_processing_reconnects_to_same_outcome(receiver, event, monkeypatch):
    from time import monotonic, sleep

    controller = receiver.controller
    controller.start('123')
    entered, release = Event(), Event()
    original = controller.receive_native
    calls = []
    def delayed(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(4)
        return original(*args, **kwargs)
    monkeypatch.setattr(controller, 'receive_native', delayed)
    try:
        with client(receiver) as first:
            greet(first)
            first.send(envelope(event))
            assert entered.wait(2)
        deadline = monotonic() + 2
        while receiver.status()['connected_senders'] and monotonic() < deadline:
            sleep(.01)
        with client(receiver) as second:
            assert greet(second)['type'] == 'ready'
            second.send(envelope(event))
            # Both the queued original and a journal replay are safe; only one event is recorded.
            release.set()
            ack = json.loads(second.recv(timeout=3))
            assert ack['type'] == 'ack' and ack['durable']
        assert len(controller.native_store.feed()) == 1
    finally:
        release.set()


def test_restart_replays_committed_result(receiver, event, settings, tmp_path):
    controller = receiver.controller
    controller.start('123')
    with client(receiver) as first:
        greet(first)
        first.send(envelope(event))
        original = json.loads(first.recv(timeout=3))
    # Reopen the same journal through an independent controller after clean shutdown.
    controller.close()
    replacement = DashboardController(settings, tmp_path)
    next_receiver = CaptureWebSocketServer(replacement, TOKEN, 0).start()
    replacement.capture_websocket = next_receiver
    try:
        replacement.start('123')
        with client(next_receiver) as ws:
            greet(ws)
            ws.send(envelope(event))
            replay = json.loads(ws.recv(timeout=3))
            assert replay['duplicate'] and replay['result']['trade_id'] == original['result']['trade_id']
    finally:
        replacement.close()


def test_slow_ack_reader_is_disconnected_without_blocking_dispatch(receiver):
    import asyncio

    async def exercise():
        class Socket:
            async def close(self, code, reason):
                self.code = code
        ws = Socket()
        slow = {'ws': ws, 'out': asyncio.Queue(1), 'closed': False, 'closer': None}
        receiver._offer(slow, {'type': 'ready'})
        receiver._offer(slow, {'type': 'ack'})
        assert slow['closed']
        await slow['closer']
        assert ws.code == 1013
    asyncio.run_coroutine_threadsafe(exercise(), receiver.loop).result(timeout=3)
