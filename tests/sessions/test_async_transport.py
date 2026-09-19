import _socket
import asyncio
import base64
import copy
import gzip
import json
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import httpx
import pytest

from matchtrader.core.errors import APIError, UnknownOutcomeError
from matchtrader.sessions.async_transport import AsyncRequestPool, PoolLease, TransportSettings
from matchtrader.sessions.matchtrader_adapter import AccountSession, MatchTraderAdapter
from matchtrader.sessions.session_manager import SessionManager


@pytest.fixture(autouse=True)
def allow_event_loop_socketpair(offline_and_cleanup, monkeypatch):
    # Windows asyncio uses a TCP loopback socketpair for its wakeup pipe.
    # Real external broker connections remain forbidden in every test.
    def local_connect(sock, address):
        assert address[0] in {"127.0.0.1", "::1"}, "External network is forbidden"
        return _socket.socket.connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_connect)


def token(exp):
    return "x." + base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=") + ".x"


@pytest.mark.parametrize(
    "values",
    [
        {"max_connections": 16},
        {"expected_concurrency": 24},
        {"max_keepalive_connections": 25},
        {"connect_timeout": 0},
        {"connect_timeout": 3},
        {"keepalive_expiry": 0},
        {"read_timeout": float("nan")},
    ],
)
def test_invalid_pool_capacity_and_timeouts_rejected(values):
    with pytest.raises(ValueError):
        TransportSettings(**values)


def test_async_requests_overlap_reuse_pool_and_reserve_refresh_capacity(settings, auth):
    now = [1000.0]
    entered, release = Event(), Event()
    seen, limits_seen = [], []
    active = [0]
    auth["token"] = token(1900)
    second = copy.deepcopy(auth["tradingAccounts"][0])
    second.update(tradingAccountId="456", tradingApiToken="account-two")
    auth["tradingAccounts"].append(second)

    async def handler(request):
        seen.append(request)
        if request.url.path.endswith("mtr-login"):
            return httpx.Response(200, json=auth)
        if request.url.path.endswith("refresh-token"):
            return httpx.Response(200, json={"token": token(2620)})
        active[0] += 1
        if active[0] == 2:
            entered.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        active[0] -= 1
        return httpx.Response(200, json={"orders": []}, headers={"set-cookie": "unexpected=private; Path=/"})

    def factory(limits):
        limits_seen.append(limits)
        return httpx.MockTransport(handler)

    config = TransportSettings(
        expected_concurrency=2, max_connections=4, max_keepalive_connections=2, pool_timeout=0.05
    )
    manager = SessionManager(clock=lambda: now[0], automatic=False)
    adapter = MatchTraderAdapter(settings, transport_settings=config, async_transport_factory=factory)
    manager.register("A", "A", adapter)
    first = AccountSession(manager, "A", settings)
    second = AccountSession(manager, "A", settings.model_copy(update={"account_id": "456"}))
    first.login()

    async def exercise():
        pending = [asyncio.create_task(a.aexecute("active_orders")) for a in (first, second)]
        try:
            assert await asyncio.to_thread(entered.wait, 2), "Requests were serialized"
            with pytest.raises(APIError):
                await first.aexecute("active_orders")
            assert adapter.transport_status()["last_failure"] == "PoolTimeout"
            now[0] = 1720
            await asyncio.to_thread(manager.refresh, "A")
            assert manager.status("A")["state"] == "connected"
        finally:
            release.set()
            assert await asyncio.gather(*pending) == [[], []]
        await first.aexecute("active_orders")

    try:
        asyncio.run(exercise())
        assert len(limits_seen) == 1
        assert limits_seen[0].max_connections == 4 and limits_seen[0].keepalive_expiry == 15
        requests = [r for r in seen if r.url.path.endswith("active-orders")]
        assert {r.headers["Auth-trading-api"] for r in requests} == {"trading-test", "account-two"}
        assert requests[-1].headers["Cookie"] == "co-auth=" + token(2620)
        assert all("unexpected" not in r.headers.get("Cookie", "") for r in seen)
        assert all(r.extensions["timeout"]["connect"] == 1.5 for r in seen)
        pool = adapter._pool
        manager.disconnect("A")
        assert pool._closed and not pool._thread.is_alive()
        auth["token"] = token(2620)
        manager.connect("A")
        assert adapter._pool is not pool
    finally:
        manager.close()


def test_connect_timeout_is_reported_and_mutation_is_never_replayed(settings, auth):
    seen = []
    auth["token"] = token(1900)

    async def handler(request):
        seen.append(request)
        if request.url.path.endswith("mtr-login"):
            return httpx.Response(200, json=auth)
        assert request.extensions["timeout"] == {"connect": 1.5, "read": 20, "write": 20, "pool": 0.25}
        raise httpx.ConnectTimeout("private network details", request=request)

    manager = SessionManager(clock=lambda: 1000, automatic=False)
    adapter = MatchTraderAdapter(
        settings, async_transport_factory=lambda limits: httpx.MockTransport(handler)
    )
    manager.register("A", "A", adapter)
    account = AccountSession(manager, "A", settings)
    account.login()
    try:
        with pytest.raises(UnknownOutcomeError) as error:
            asyncio.run(
                account.aexecute(
                    "create_pending_order",
                    instrument="XAUUSD",
                    orderSide="BUY",
                    type="LIMIT",
                    volume=1,
                    price=4340,
                    slPrice=4330,
                    tpPrice=4350,
                )
            )
        assert "private" not in str(error.value)
        assert len(seen) == 2
        assert manager.status("A")["transport"]["last_failure"] == "ConnectTimeout"
    finally:
        manager.close()


def test_pool_does_not_open_socket_until_requested_and_closes_idempotently():
    pool = AsyncRequestPool()
    assert pool._loop is None and pool._transport is None
    PoolLease(pool).close()
    assert not pool._closed
    pool.close()
    pool.close()
    with pytest.raises(RuntimeError):
        pool.request(httpx.Request("GET", "https://broker.example"))


def test_real_async_pool_reuses_socket_then_retires_it_after_idle_expiry():
    ports = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            ports.append(self.client_address[1])
            body = gzip.compress(b'{"ok":true}')
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    pool = AsyncRequestPool(TransportSettings(keepalive_expiry=0.1))
    try:
        # Each SDK-style client is short lived, but the broker's pool is shared.
        def request():
            with httpx.Client(transport=PoolLease(pool), trust_env=False) as client:
                return client.get(f"http://127.0.0.1:{server.server_port}/orders").json()

        assert request() == {"ok": True}
        assert request() == {"ok": True}
        assert ports[0] == ports[1]
        time.sleep(0.2)
        assert request() == {"ok": True}
        assert ports[2] != ports[1]
    finally:
        pool.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_cancelled_await_does_not_replay_trade_and_disconnect_drains_socket(settings, auth):
    auth["token"] = token(1900)
    entered, release = Event(), Event()
    trades = []

    async def handler(request):
        if request.url.path.endswith("mtr-login"):
            return httpx.Response(200, json=auth)
        trades.append(request)
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        return httpx.Response(200, json={"status": "OK", "orderId": "test-only"})

    manager = SessionManager(clock=lambda: 1000, automatic=False)
    adapter = MatchTraderAdapter(
        settings, async_transport_factory=lambda limits: httpx.MockTransport(handler)
    )
    manager.register("A", "A", adapter)
    manager.connect("A")

    async def exercise():
        task = asyncio.create_task(
            manager.aexecute(
                "A",
                "123",
                "create_pending_order",
                instrument="XAUUSD",
                orderSide="BUY",
                type="LIMIT",
                volume=1,
                price=4340,
            )
        )
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        closed = Event()

        def disconnect():
            manager.disconnect("A")
            closed.set()

        worker = Thread(target=disconnect)
        worker.start()
        try:
            assert not await asyncio.to_thread(closed.wait, 0.03)
        finally:
            release.set()
            await asyncio.to_thread(worker.join, 2)
        assert closed.is_set()

    try:
        asyncio.run(exercise())
        assert len(trades) == 1
        assert adapter._pool is None
    finally:
        release.set()
        manager.close()
