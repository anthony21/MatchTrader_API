"""Broker-owned async socket pool with a synchronous bridge for the frozen SDK."""

import asyncio
from threading import RLock, Thread

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TransportSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    expected_concurrency: int = Field(default=16, ge=1, le=512)
    max_connections: int = Field(default=24, ge=3, le=1024)
    max_keepalive_connections: int = Field(default=16, ge=0, le=1024)
    keepalive_expiry: float = Field(default=15, gt=0, le=300)
    connect_timeout: float = Field(default=1.5, gt=0, le=2)
    read_timeout: float = Field(default=20, gt=0, le=300)
    write_timeout: float = Field(default=20, gt=0, le=300)
    pool_timeout: float = Field(default=0.25, gt=0, le=10)

    @model_validator(mode="after")
    def capacity(self):
        if self.max_connections < self.expected_concurrency + 2:
            raise ValueError("max_connections must exceed expected_concurrency with two renewal slots")
        if self.max_keepalive_connections > self.max_connections:
            raise ValueError("max_keepalive_connections cannot exceed max_connections")
        return self


class AsyncRequestPool:
    """One lazy event loop and reusable async transport per broker.

    Authentication is NOT stored in the pool. The SDK supplies per-request
    headers; responses return to its isolated cookie jar. Socket I/O is async,
    while existing SDK callers can stay synchronous.
    """

    def __init__(self, config=None, *, transport_factory=None):
        self.config = config or TransportSettings()
        self._factory = transport_factory
        self._lock = RLock()
        self._loop = None
        self._thread = None
        self._transport = None
        self._slots = None
        self._pending = set()
        self._closed = False
        self.last_failure = None

    def _start(self):
        if self._closed:
            raise RuntimeError("Broker transport is closed")
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._thread = Thread(target=self._serve, name="broker-async-http", daemon=True)
            self._thread.start()

    def _serve(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    async def _request(self, request):
        if self._transport is None:
            limits = httpx.Limits(
                max_connections=self.config.max_connections,
                max_keepalive_connections=self.config.max_keepalive_connections,
                keepalive_expiry=self.config.keepalive_expiry,
            )
            self._transport = (
                self._factory(limits)
                if self._factory
                else httpx.AsyncHTTPTransport(limits=limits, retries=0, trust_env=False)
            )
            self._slots = asyncio.Semaphore(self.config.expected_concurrency)
        # Renewal has reserved pool headroom and never waits for trading slots.
        trading = not request.url.path.startswith("/manager/")
        acquired = False
        try:
            if trading:
                try:
                    await asyncio.wait_for(self._slots.acquire(), self.config.pool_timeout)
                    acquired = True
                except TimeoutError:
                    raise httpx.PoolTimeout(
                        "Broker concurrency capacity exhausted", request=request
                    ) from None
            request.extensions["timeout"] = {
                "connect": self.config.connect_timeout,
                "read": self.config.read_timeout,
                "write": self.config.write_timeout,
                "pool": self.config.pool_timeout,
            }
            # Raw transport avoids shared client cookies between accounts.
            response = await self._transport.handle_async_request(request)
            try:
                chunks = [chunk async for chunk in response.stream]
                # A raw stream preserves content encoding for the SDK client.
                return httpx.Response(
                    response.status_code, headers=response.headers, stream=httpx.ByteStream(b"".join(chunks))
                )
            finally:
                await response.aclose()
        except httpx.TransportError as exc:
            self.last_failure = type(exc).__name__
            raise
        finally:
            if acquired:
                self._slots.release()

    def request(self, request):
        with self._lock:
            self._start()
            future = asyncio.run_coroutine_threadsafe(self._request(request), self._loop)
            self._pending.add(future)
        try:
            return future.result()
        finally:
            with self._lock:
                self._pending.discard(future)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pending = list(self._pending)
        for future in pending:
            try:
                future.result()
            except Exception:
                pass
        if self._loop:
            if self._transport:
                asyncio.run_coroutine_threadsafe(self._transport.aclose(), self._loop).result()
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()

    def status(self):
        return {**self.config.model_dump(), "io": "async", "last_failure": self.last_failure}


class PoolLease(httpx.BaseTransport):
    """Per-request SDK views do not own the reusable broker pool."""

    def __init__(self, pool):
        self.pool = pool

    def handle_request(self, request):
        return self.pool.request(request)

    def close(self):
        pass
