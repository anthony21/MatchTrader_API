# Asynchronous broker HTTP transport

The application adapter uses one lazy `httpx.AsyncHTTPTransport` pool per broker.
HTTP requests execute on that broker's asyncio event loop. The pool owns sockets,
not authentication: every request receives explicit headers from its account's
token snapshot, and response cookies return to an isolated SDK view. Account
switches reuse the same broker pool. Different brokers have different pools.

The original synchronous SDK facade, endpoint models, validation, response
parsing and error contracts remain unchanged. Existing dashboard/capture callers
use a synchronous compatibility bridge to async I/O. Async consumers use:

```python
orders, positions = await asyncio.gather(
    account.aexecute("active_orders"),
    account.aexecute("open_positions"),
)
```

The unchanged SDK executes in a broker-scoped worker executor so its synchronous
validation and rate-limit waits do not block the caller's event loop. The socket
operation itself uses async I/O. This does not convert the dashboard server or
its capture sequencing to an async framework, or remove ordering locks on trade
lifecycle operations. It does not claim measured latency improvements at a broker.

## Defaults and per-broker overrides

| Setting | Default |
| --- | ---: |
| Expected simultaneous trading requests | 16 |
| Maximum connections | 24 |
| Maximum idle keep-alive connections | 16 |
| Keep-alive expiry | 15 seconds |
| Connect timeout | 1.5 seconds |
| Read / write timeouts | 20 / 20 seconds |
| Pool / admission timeout | 0.25 seconds |

The default concurrency is an initial sizing assumption, not a measurement of
production load. Change these private `.env` settings and restart to size a broker:

```dotenv
# Primary broker uses MTR_; GooeyTrade uses GTR_.
MTR_HTTP_EXPECTED_CONCURRENCY=32
MTR_HTTP_MAX_CONNECTIONS=40
MTR_HTTP_MAX_KEEPALIVE_CONNECTIONS=32
MTR_HTTP_KEEPALIVE_EXPIRY=15
MTR_HTTP_CONNECT_TIMEOUT=1.5
MTR_HTTP_READ_TIMEOUT=20
MTR_HTTP_WRITE_TIMEOUT=20
MTR_HTTP_POOL_TIMEOUT=0.25
GTR_HTTP_EXPECTED_CONCURRENCY=16
GTR_HTTP_MAX_CONNECTIONS=24
```

Configuration rejects max_connections below expected concurrency plus two
reserved authentication slots. Trading requests use bounded admission; renewal
bypasses those slots so a fully occupied trading workload does not starve it.
Bursts above configured concurrency can queue briefly or fail with PoolTimeout.
SDK broker rate limits still apply. More sockets cannot eliminate all queueing.

Keep-alive expiry makes idle sockets ineligible for reuse after the configured
duration. It is not a heartbeat or a guarantee against remote disconnections.
Tests use a real loopback HTTP/1.1 server to verify reuse before expiry and a new
socket after expiry, including compressed responses.

Connect timeout is separate from read/write and pool timeouts. Status includes
the effective configuration and the last transport failure class, without
credentials or upstream messages. HTTPX automatic connection retries are disabled.
No alternate broker gateway is configured, so automatic endpoint failover is not
implemented. Timed-out trades are never replayed automatically; the existing SDK
conservatively reports an uncertain mutation outcome for transport failures.

Cancelling an async await does not prove cancellation of a dispatched order.
Disconnect prevents new requests, waits for in-flight requests, closes the pool,
and invalidates queued work from the previous session. Application shutdown also
stops the worker executors. No sockets are opened merely by starting the app.

References: [HTTPX async transports](https://www.python-httpx.org/async/),
[pool limits](https://www.python-httpx.org/advanced/resource-limits/), and
[timeout types](https://www.python-httpx.org/advanced/timeouts/).
