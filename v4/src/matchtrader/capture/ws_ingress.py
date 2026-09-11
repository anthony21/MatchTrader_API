"""Authenticated loopback WebSocket ingress with bounded admission and FIFO dispatch."""

import asyncio
import hmac
import json
from datetime import UTC, datetime
from http import HTTPStatus
from threading import Event, Lock, Thread
from time import perf_counter_ns

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from . import ws_protocol as protocol
from .dispatch_metrics import DispatchMetrics


class CaptureWebSocketServer:
    def __init__(self, controller, token, port=8767, *, queue_limit=256, max_inflight=32):
        if not token or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError('Configure MTR_BRIDGE_TOKEN before enabling WebSocket capture')
        if not 0 <= port <= 65535 or queue_limit < 1 or max_inflight < 1:
            raise ValueError('Invalid WebSocket receiver limits')
        self.controller, self.token, self.port = controller, token, port
        self.queue_limit, self.max_inflight = queue_limit, max_inflight
        self.metrics = DispatchMetrics()
        self.raw_log = controller.native_store.raw_log
        self.guard = Lock()
        self.health = {'listening': False, 'connected_senders': 0, 'machines': [], 'queued': 0,
                       'in_progress': 0, 'received': 0, 'acknowledged': 0, 'rejected': 0,
                       'last_event_at': None, 'last_error': None}
        self.ready = Event()
        self.thread = None
        self.failure = None

    def _health(self, **values):
        with self.guard:
            self.health.update(values)

    def _count(self, key):
        with self.guard:
            self.health[key] += 1

    def status(self):
        with self.guard:
            result = dict(self.health)
        return {**result, 'endpoint': f'ws://127.0.0.1:{self.port}{protocol.PATH}',
                'transport_version': protocol.VERSION, 'metrics': self.metrics.snapshot()}

    def start(self):
        if self.thread:
            raise RuntimeError('Receiver already started')
        self.thread = Thread(target=self._thread_main, name='capture-websocket', daemon=True)
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError('WebSocket receiver startup timed out')
        if self.failure:
            raise RuntimeError('WebSocket receiver could not start; check the configured port') from self.failure
        return self

    def _thread_main(self):
        try:
            asyncio.run(self._run())
        except Exception as exc:
            self.failure = exc
            self._health(listening=False, last_error='Receiver stopped unexpectedly')
        finally:
            self.ready.set()

    async def _run(self):
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()
        self.jobs = asyncio.Queue(self.queue_limit)
        self.pending = {}
        self.clients = set()
        self.machines = {}
        self.accepting = True
        async with serve(self._handle, '127.0.0.1', self.port, subprotocols=[protocol.SUBPROTOCOL],
                         process_request=self._upgrade, compression=None, origins=[None],
                         max_size=protocol.MAX_MESSAGE, max_queue=16, ping_interval=5,
                         ping_timeout=10, close_timeout=2, open_timeout=5, server_header=None) as server:
            self.port = server.sockets[0].getsockname()[1]
            self._health(listening=True)
            self.ready.set()
            worker = asyncio.create_task(self._worker())
            await self.stop_event.wait()
            self.accepting = False
            server.close()
            await self.jobs.put(None)
            await worker
        self._health(listening=False, connected_senders=0, machines=[])

    def close(self):
        if self.thread and self.thread.is_alive() and hasattr(self, 'loop'):
            self.loop.call_soon_threadsafe(self.stop_event.set)
            self.thread.join()  # Finish a claimed request before the controller/journal closes.

    def _upgrade(self, connection, request):
        try:
            headers = request.headers
            allowed_host = {f'127.0.0.1:{self.port}', f'localhost:{self.port}'}
            if request.path != protocol.PATH:
                return connection.respond(HTTPStatus.NOT_FOUND, 'Unknown capture endpoint\n')
            if headers.get('Host') not in allowed_host or headers.get('Origin') is not None:
                return connection.respond(HTTPStatus.FORBIDDEN, 'Native loopback clients only\n')
            if not hmac.compare_digest(headers.get('Authorization', '').encode(), ('Bearer ' + self.token).encode()):
                return connection.respond(HTTPStatus.UNAUTHORIZED, 'Sender authentication required\n')
            if protocol.SUBPROTOCOL not in [s.strip() for s in headers.get('Sec-WebSocket-Protocol', '').split(',')]:
                return connection.respond(HTTPStatus.BAD_REQUEST, 'Required capture subprotocol missing\n')
        except Exception:
            return connection.respond(HTTPStatus.BAD_REQUEST, 'Invalid handshake\n')
        if len(self.clients) >= 8 or not self.accepting:
            return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, 'Receiver busy\n')
        return None

    def _reject(self, client, code, identity=None):
        self._count('rejected')
        self._health(last_error=code)
        self._offer(client, protocol.nack(code, identity))

    def _offer(self, client, message, release=False):
        if client['closed']:
            return
        try:
            client['out'].put_nowait((message, release))
        except asyncio.QueueFull:
            # No network I/O in the dispatch worker; reconnect recovers durable results.
            client['closed'] = True
            client['closer'] = asyncio.create_task(client['ws'].close(1013, 'Slow acknowledgement reader'))

    async def _writer(self, client):
        try:
            while True:
                message, release = await client['out'].get()
                await asyncio.wait_for(client['ws'].send(json.dumps(message)), timeout=5)
                self.raw_log.append('out', 'websocket', message, self.token)
                identity = message.get('event_id')
                if identity and release:
                    client['inflight'].discard(identity)
        except (ConnectionClosed, TimeoutError):
            await client['ws'].close(1013, 'Acknowledgement delivery unavailable')

    async def _handle(self, ws):
        if len(self.clients) >= 8:
            await ws.close(1013, 'Receiver busy')
            return
        self.clients.add(ws)
        machine = None
        writer = None
        client = {'ws': ws, 'out': asyncio.Queue(64), 'inflight': set(), 'closed': False, 'closer': None}
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=5)
            self.raw_log.append('in', 'websocket', first, self.token)
            if not isinstance(first, str):
                await ws.close(1003, 'Text JSON required')
                return
            machine = protocol.hello(protocol.decode(first))
            if machine in self.machines:
                self.raw_log.append('out', 'websocket', protocol.nack('sender_busy'), self.token)
                await ws.send(json.dumps(protocol.nack('sender_busy')))
                await ws.close(1008, 'Machine already connected')
                return
            self.machines[machine] = client
            self._health(connected_senders=len(self.machines), machines=list(self.machines))
            writer = asyncio.create_task(self._writer(client))
            self._offer(client, {'type': 'ready', 'transport_version': protocol.VERSION,
                                'event_schema_version': '1.1.0', 'max_inflight': self.max_inflight,
                                'capture_running': self.controller.running,
                                'copying_armed': self.controller.native.armed})
            async for raw in ws:
                received = perf_counter_ns()
                self.raw_log.append('in', 'websocket', raw, self.token)
                if not isinstance(raw, str):
                    await ws.close(1003, 'Text JSON required')
                    break
                try:
                    event = protocol.event(protocol.decode(raw), machine)
                except protocol.ProtocolFault as exc:
                    self._reject(client, exc.code, exc.event_id)
                    continue
                self._admit(client, event, received, perf_counter_ns())
        except protocol.ProtocolFault as exc:
            self.raw_log.append('out', 'websocket', protocol.nack(exc.code, exc.event_id), self.token)
            await ws.send(json.dumps(protocol.nack(exc.code, exc.event_id)))
            await ws.close(1008, 'Invalid capture hello')
        except TimeoutError:
            await ws.close(1008, 'Capture hello timed out')
        except ConnectionClosed:
            pass
        finally:
            client['closed'] = True
            if writer:
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
            if client['closer']:
                await asyncio.gather(client['closer'], return_exceptions=True)
            if machine and self.machines.get(machine) is client:
                self.machines.pop(machine)
            self.clients.discard(ws)
            self._health(connected_senders=len(self.machines), machines=list(self.machines))

    def _admit(self, client, event, received, validated):
        if not self.accepting or not self.controller.running:
            return self._reject(client, 'capture_stopped', event.event_id)
        if len(client['inflight']) >= self.max_inflight and event.event_id not in client['inflight']:
            return self._reject(client, 'busy', event.event_id)
        key = (event.machine, event.event_id)
        existing = self.pending.get(key)
        if existing:
            if existing['event'] != event:
                return self._reject(client, 'identity_conflict', event.event_id)
            if not any(waiter is client for waiter in existing['waiters']):
                existing['waiters'] = [waiter for waiter in existing['waiters'] if not waiter['closed']]
                existing['waiters'].append(client)
            client['inflight'].add(event.event_id)
            return
        if self.jobs.full():
            return self._reject(client, 'busy', event.event_id)
        job = {'event': event, 'received': received, 'validated': validated, 'waiters': [client],
               'generation': self.controller.capture_generation}
        self.pending[key] = job
        client['inflight'].add(event.event_id)
        self.jobs.put_nowait(job)
        self._count('received')
        self._health(last_event_at=datetime.now(UTC).isoformat(), queued=self.jobs.qsize())

    def _process(self, job):
        event = job['event']
        return self.metrics.run(event, job['received'], job['validated'], lambda:
            self.controller.receive_native(event.model_dump(mode='json'), capture_generation=job['generation']))

    async def _worker(self):
        while True:
            job = await self.jobs.get()
            if job is None:
                break
            event = job['event']
            self._health(queued=self.jobs.qsize(), in_progress=1)
            try:
                if self.stop_event.is_set():
                    response = protocol.nack('capture_stopped', event.event_id)
                else:
                    result = await asyncio.to_thread(self._process, job)
                    response = protocol.ack(result)
                    self._count('acknowledged')
            except ValueError as exc:
                code = 'capture_stopped' if str(exc) == 'Capture is stopped' else 'identity_conflict'
                response = protocol.nack(code, event.event_id)
            except Exception:
                # No durable ACK on storage/processing failure. Replays still hit the journal claim.
                response = protocol.nack('busy', event.event_id)
                self._health(last_error='Processing unavailable; journal retained')
            if response['type'] == 'nack':
                self._count('rejected')
            self.pending.pop((event.machine, event.event_id), None)
            for client in job['waiters']:
                self._offer(client, response, release=True)
            self._health(in_progress=0)
