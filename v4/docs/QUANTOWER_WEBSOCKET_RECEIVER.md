# Quantower WebSocket receiver - application 0.5.0

The Python receiver is implemented. This does not install or change the Quantower
extension. Use transport contract 1.0.0 and capture event schema 1.1.0 from
[the shared plan](QUANTOWER_WEBSOCKET_PLAN.md).

## Sender connection values

- URL: `ws://127.0.0.1:8767/capture/ws` when both processes are on this machine.
- Subprotocol: `hcamm.capture.v1` (required).
- Upgrade header: `Authorization: Bearer <MTR_BRIDGE_TOKEN>`.
- The token is the existing private `.env` value; do not put it in a URL or event.
- Send hello first, wait for ready, then send event envelopes.
- Read terminal ACKs by event_id. Delete an outbox record only after durable=true.

The receiver starts with the dashboard when a bridge token is configured. Its port
comes from `MTR_CAPTURE_WS_PORT`, default 8767. `--ws-port 8767` overrides it;
`--ws-port 0` disables it. Missing token disables the default receiver; explicitly
requesting a port without a token fails startup. Port conflicts fail visibly.
Only loopback is supported in this release; remote WSS deployment is not included.

Run from v4 using its environment:

```powershell
.\.venv\Scripts\python.exe -m matchtrader.dashboard.cli
```

Click **Start capture** to accept new events. The socket can connect while capture
is stopped, but events then receive retryable capture_stopped NACKs. API trading is
separately disarmed by default and must satisfy the existing demo and route checks.
A connected sender does not arm copying or establish broker acceptance.

## Implemented behavior

- Strict hello/event envelopes and versions; duplicate JSON keys rejected.
- Native-client upgrade authentication, path/Host/subprotocol validation, no browser Origin.
- 32 KiB text messages, 16 KiB event limit, native fragmentation and Ping/Pong.
- One connection per machine, eight clients, 32 outstanding events per sender,
  a bounded 256-event queue, one FIFO dispatcher and a separate ACK writer per socket.
- Identical in-progress retries attach to the existing result. Persistent replay
  uses the same journal as HTTP ingress; altered payloads receive identity_conflict.
- Stop/start generation checking rejects queued work from an earlier capture session.
- Pending work survives socket loss in process. After a process restart, the sender
  replays its retained outbox into persistent deduplication. Claimed/uncertain broker
  attempts are never automatically retried. Duplicate responses expose uncertain
  state and existing broker IDs where known.
- Full/slow ACK queues close the connection; no socket write holds the dispatcher.
- Shutdown closes admission and rejects queued work; an already executing request
  completes before its journal is closed. No broker mutation is cancelled or retried
  merely because the sender disconnected.
- CSV exports are coalesced in a background worker; SQLite event/attempt commits
  remain synchronous. CSV file writes do not hold the journal lock.

Old version-1 outbox records should be drained using the existing HTTP transport
before switching to the 1.1.0 WebSocket sender. Do not rewrite previously delivered
events or their schema version while keeping the same event ID; a changed replay
correctly produces identity_conflict. Do not run both delivery transports at once.

## Frontend and timing

Incoming trades now separates **Quantower WebSocket** from **Live push** (the
backend-to-browser SSE connection). It shows waiting/connected state, machine names,
receiver queue/processing/ACK counts, last receipt/error and dispatch metrics.
Receiver queue counts are not the sender's durable outbox count; v1 doesn't report
that count. Status indicators update with the existing dashboard status poll.
Native event rows continue to arrive through SSE as journal changes occur.

Timing begins when the application receives a complete WebSocket message. It ends
at HTTP-core's outbound request-header write-start trace event, after broker pacing.
This is transport initiation, not proof that Aqua received a packet or filled an
order. The trace ignores header/socket data and keeps no credentials. The last 500
processed event samples are held in memory; timing history resets at application
restart. Aggregate metrics include p50/p95/p99/max, measured write count, no-write
sample count, and percentage under 10 ms. The latest sample includes queue,
validation, commit/preflight/pacing and response spans when applicable.

**Under 10 ms is not certified.** Existing instrument/position preflight reads and
aggregate broker pacing remain in force. We removed synchronous CSV I/O from the
path, but did not add unverified caches, relax broker limits, or remove durable
claims. An observation/held event with no traced outbound write says Not measured,
not zero milliseconds. A target miss doesn't silently drop or retry a trade.

## Validation and limits

Python tests exercise handshake rejection, fragmentation, size limits, source
binding, stopped capture, duplicates across ingress paths, changed-payload rejection,
reconnect during processing, restart replay, bounded admission and generation checks.
Existing router tests cover partial fills, position ambiguity and lifecycle holds.
Metrics tests verify that timing starts at the transport trace after pacing.

A standalone .NET 10 ClientWebSocket test client in `scripts/ws_smoke_client/` was
run against an isolated receiver with a fake Aqua API. CREATE, EDIT and CANCEL each
produced one fake broker call; replay generated durable duplicate ACKs with the same
trade ID. This proves C# transport interoperability, not installed Quantower callback
behavior or live Aqua execution. The test client must only target an isolated test
receiver with a fake broker; it is not a production sender or a deployment command.

Final release checks: **286 Python tests, 30 frontend tests, six Chrome browser
checks**, the .NET ClientWebSocket interoperability smoke test, Ruff, Poetry metadata
checks and production frontend build all passed. No live Aqua writes were tested.
