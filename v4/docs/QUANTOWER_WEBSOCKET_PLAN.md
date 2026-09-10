# Quantower WebSocket sender and receiver design

Status: receiver implemented in application 0.5.0. See
[receiver setup and verified limits](QUANTOWER_WEBSOCKET_RECEIVER.md).
This document retains the shared design and later optimization phases.
Transport contract: 1.0.0. Capture event schema: existing 1.1.0.

## Objective and topology

Quantower callback -> durable C# outbox -> persistent WebSocket -> Python ingress
-> existing capture journal and router -> existing account-scoped Aqua REST client.
The dashboard continues receiving SSE; browser rendering is outside this path.

Target: less than 10 ms from receiving a complete WebSocket event message to the
HTTP transport beginning the outbound Aqua request, on a ready/warm path. This is
a measurement target, not an execution guarantee. Include parsing, queue waits,
validation, journal commits, locks and rate-limit waits in that interval. Record
broker response and fill timings separately. Sender callback-to-send is a separate
measurement and must include sender outbox persistence.

Current obstacles found in source:

- DurableOutbox.Start waits up to 250 ms while idle before checking for work.
- RateLimiter spaces calls by 60 / requests_per_minute; the default 450 means
  approximately 133 ms between requests sharing the same broker origin. This is
  the application's configured pacing, not a newly verified Aqua rate limit.
- CaptureRouter validates instruments with a broker read. Edit/cancel/close also
  query pending orders and positions before the mutation.
- CSV export runs synchronously during journal operations.
- The controller/router currently serialize work around synchronous broker calls.

WebSocket transport alone does not remove these delays. Preserve durable dispatch
claims, attribution checks, demo routing, quantity checks and unknown-outcome holds.

## Shared connection contract

| Setting | Proposed value |
| --- | --- |
| Receiver address on the same machine | ws://127.0.0.1:8767/capture/ws |
| Existing dashboard/HTTP ingress | Port 8765; unchanged |
| Subprotocol | hcamm.capture.v1 |
| Authentication | Authorization: Bearer <existing MTR_BRIDGE_TOKEN> during upgrade |
| Encoding | UTF-8 JSON, one envelope per complete text message |
| Event limit | 16,384 UTF-8 bytes for the serialized event object |
| Message limit | 32,768 bytes after fragment reassembly; binary messages rejected |
| Compression | Disabled initially |
| Heartbeat | Receiver WebSocket Ping every 5 seconds; Pong timeout 10 seconds |
| Initial hello deadline | 5 seconds after upgrade |
| Outstanding events | Receiver advertises max_inflight=32 initially |
| Receiver work queue | Bounded, 256 events globally initially |
| Socket connections | Bounded, 8 authenticated clients initially |

8767 is a proposed new listener owned by the dashboard process. It is deliberately
separate from the existing HTTP server and the 8766 browser-test fixture. Launch
and shut it down with the dashboard; a requested listener failing to bind is a
visible startup failure. Never automatically arm copying when it connects.

Same-machine default binds loopback only. The token stays in local configuration,
never query strings, event payloads or logs. Validate path, Host, token and required
subprotocol before accepting events; reject browser Origin headers for this native
sender endpoint. A different-machine deployment requires an explicitly configured
wss:// endpoint and certificate validation, rather than exposing plain ws publicly.
No Aqua credentials or session tokens are supplied to Quantower.

The C# client proposes the subprotocol and verifies it was selected. It must assemble
fragmented messages up to the message limit. After upgrade it sends:

```json
{"type":"hello","transport_version":"1.0.0","event_schema_version":"1.1.0","machine":"QT-WORKSTATION","sender_instance_id":"7e0461ac-43dd-491c-9f9d-c9a7ac686953"}
```

`machine` is the existing stable event/deduplication identity; do not regenerate it
on reconnect. `sender_instance_id` is a diagnostic process UUID, not a trade key.
Permit one active connection per machine: reject a second with a retryable
sender_busy error until the first closes or its heartbeat expires. Do not silently
run two publishers or replace one that still has queued actions.

Receiver responds:

```json
{"type":"ready","transport_version":"1.0.0","event_schema_version":"1.1.0","max_inflight":32,"capture_running":true,"copying_armed":false}
```

Ready means compatible/authenticated transport. Capture and copying states are
informational snapshots and must be rechecked for every event. It does not authorize
trading. Sender begins delivery only after ready; when capture is stopped it retains
the outbox and retries with backoff, without changing original event timestamps.

## Event envelope

```json
{
  "type":"event",
  "transport_version":"1.0.0",
  "event":{
    "schema_version":"1.1.0",
    "event_id":"qt-session-01:00000142",
    "machine":"QT-WORKSTATION",
    "connection_id":"quantower-connection-id",
    "account_id":"quantower-internal-account-id",
    "order_id":"qt-order-9821",
    "position_id":"",
    "execution_id":"",
    "request_id":"qt-request-142",
    "emitted_at":"2026-09-10T17:30:00.123456Z",
    "kind":"ACCEPTED",
    "action":"CREATE",
    "source":"R01",
    "sending_source":"HCAMM:R01",
    "source_label":"",
    "snapshot":false,
    "symbol":"EURUSD",
    "side":"BUY",
    "order_type":"LIMIT",
    "quantity":"1",
    "quantity_unit":"native",
    "price":"1.15000",
    "sl":"1.14980",
    "tp":"1.16000",
    "brackets_absolute":true,
    "fill_effect":"UNKNOWN"
  }
}
```

The example's timestamp is illustrative; new events use the actual UTC instant.
Resends use the identical saved event, including IDs and emitted_at. Envelope
metadata must not leak into CaptureEvent, which rejects extra fields.

Reuse docs/schemas/capture-event-1.1.0.json without a competing C# field contract.
Numbers are invariant-culture decimal strings, not rounded floating point values.
Preserve machine/connection/account scope and native order, position, request and
execution IDs. Never substitute a position ID for an order ID. Preserve explicit
R01/X17/P01/manual attribution; blanks stay UNKNOWN. Fill effect is OPEN/CLOSE only
when directly established; otherwise UNKNOWN. Send available order/cumulative/
remaining/position quantities for partial fills without inventing them.

Only existing eligible ACCEPTED events with CREATE/EDIT/CANCEL/CLOSE can trigger
copying. REQUEST, ORDER, FILL, POSITION, SIGNAL and ACCOUNT remain observations.
A FILL after ACCEPTED must not open a second copied trade. SIGNAL does not become
an executable order. Startup inventory is snapshot=true and never dispatches.

## Acknowledgements, retries and ordering

Version 1 uses one terminal acknowledgement after the existing router finishes
processing and the journal decision is committed. No early memory-only receipt.
The socket reader and ACK reader continue running independently of broker work.

```json
{"type":"ack","transport_version":"1.0.0","event_id":"qt-session-01:00000142","durable":true,"duplicate":false,"result":{"schema_version":"1.1.0","event_id":"qt-session-01:00000142","trade_id":"30cbb7da-ef16-43cd-a63c-78843e83b833","status":"held","reason":"Copying is not armed with a verified demo destination","broker_order_id":"","broker_position_id":""}}
```

Result follows the existing router response: captured/held/accepted/uncertain.
`accepted` means broker request acceptance, not necessarily a fill. An ACK may take
longer than 10 ms because it includes broker processing; it is not the dispatch
latency target. Sending later events does not wait for each earlier ACK: respect
max_inflight instead, while retaining source order in the send queue.

Delete an outbox entry only after a matching ACK with durable=true. Save its result
in the sender's acknowledgement log first. ACKs may arrive out of order; correlate
by event_id, never by the oldest filename. held and uncertain are durable outcomes
and are not automatic retries. Unknown/malformed ACKs never delete pending entries.

Negative acknowledgements have the following shape:

```json
{"type":"nack","transport_version":"1.0.0","event_id":"qt-session-01:00000142","code":"capture_stopped","retryable":true}
```

Retryable codes: capture_stopped, busy, sender_busy (hello errors may omit event_id).
Permanent codes: invalid_event, unsupported_version, identity_conflict,
machine_mismatch. Quarantine permanent failures with their original payload; do
not silently drop them or let one poison event block the entire outbox. Authentication
failure pauses delivery and surfaces a configuration fault. Oversize/binary messages
close the connection with the appropriate WebSocket protocol error.

Queue admission occurs before processing. On a full queue NACK busy without an ACK;
the sender retains the record. When the 32-event in-flight window is exhausted,
stop sending until an ACK/NACK releases capacity. Use one FIFO execution worker in
phase 1, preserving the current serialized router. This intentionally limits
throughput while maintaining lifecycle order. Partitioning by destination account
is a later measured optimization, never parallel dispatch on the same trade.

Reconnect with exponential backoff 250 ms to 5 seconds plus jitter. Resend pending
records in durable outbox order with the same IDs and payloads. Keep one send loop
and one receive loop per ClientWebSocket; do not overlap multiple SendAsync calls.
Use actual Ping/Pong handling supported by the installed .NET runtime, not fake
trade events. ACK inactivity alone is not a reconnect reason if heartbeats work;
broker processing can legitimately be slow. Surface stuck-work health separately.

Deduplicate queued/in-progress events by (machine,event_id) and validated payload
identity, then reuse persistent CaptureStore deduplication across restarts and HTTP.
An identical in-progress resend attaches to the existing outcome; it never dispatches
again. Conflicting payloads receive identity_conflict. Recheck capture/arming, event
age, route and exact mappings at dispatch time, including after queue waits.
The existing 30-second age and pre-arming checks remain in force.

Disconnect does not cancel admitted work. If dispatch occurred but ACK was lost,
replay returns the journal result. If the receiver crashed during a claimed write,
retain uncertain state and reconcile; never send again to obtain an ACK. Preserve
current conservative crash semantics even if this holds an event that might not
have reached Aqua. This is at-most-once dispatch attempts, not exactly-once fills.
Do not run automatic HTTP fallback and WebSocket delivery simultaneously. HTTP
remains a manually selected compatibility transport sharing the same journal.

## Sender implementation ownership (other C# session)

1. Add WebSocketCaptureTransport behind a transport interface; retain the HTTP
   implementation for explicit compatibility selection in CaptureConfig.
2. Preserve DurableOutbox.Enqueue's persisted IDs and flush-before-send behavior.
   Wake the sender using a Channel/SemaphoreSlim after persistence, replacing the
   idle 250 ms scan. Recover pending disk records once at startup/reconnect.
3. Keep network operations off Quantower callbacks. Serialize callback order into
   the durable outbox; a wakeup carries availability, not the only copy of the event.
4. Implement hello/ready, one send loop, one ACK receive loop, bounded in-flight
   tracking, correlation, fragment handling, heartbeat and cancellation.
5. Preserve source mapping and capture event semantics. Publish connection health,
   pending count, oldest pending age, reconnects and ACK results without tokens.
6. Test reconnect/lost ACK/replay, queue saturation, malformed/conflicting events,
   partial frames, process restart, culture-independent decimals, fills and manual
   changes to strategy-origin trades. Build against installed Quantower assemblies.

Proposed sender configuration additions (not accepted by current config yet):
`transport: websocket`, `websocket_endpoint: ws://127.0.0.1:8767/capture/ws`,
`websocket_subprotocol: hcamm.capture.v1`. Existing token, outbox, max_pending and
sources retain their meaning. Never switch transport implicitly during a send.

## Receiver implementation ownership (this workspace)

Proposed files, each with a dedicated test module:

| File | Responsibility |
| --- | --- |
| capture/ws_protocol.py | Strict envelopes, version negotiation, size/error codes |
| capture/ws_ingress.py | Upgrade authentication, connection lifecycle, hello binding, queues and single socket writer |
| capture/dispatch_metrics.py | Correlated monotonic spans, percentiles and miss reasons |
| dashboard/cli.py | Optional listener config, lifecycle, startup failure handling |
| dashboard/controller.py | Shared dispatch entry point; route/capture rechecks |
| capture/store.py | Existing dedup/claims; move CSV export to a coalescing worker |
| capture/router.py | Preserve semantics; instrument before optimizing preflight |
| core/rest_connection.py | Transport-start instrumentation after limiter/preflight |
| core/rate_limiter.py | Report pacing waits; no unverified rate-limit relaxation |

Use the installed websockets server API rather than implementing WebSocket framing.
Own the listener in the dashboard process with its own socket/thread lifecycle.
Give each connection one writer for ready/ACK/NACK traffic and a bounded outbound
queue; a slow client must not hold the dispatch worker during socket writes. Close
slow clients and let journal replay recover their acknowledgements. Socket readers
perform bounded admission; broker work executes through the existing shared router.
HTTP and WebSocket ingress must share identity/conflict handling and route controls.
Never hold admission/connection locks while waiting on the broker. Audit controller
and journal lock order before narrowing existing locks. Shutdown stops admission,
disarms future dispatch, drains or rejects queued work, and leaves in-flight writes
uncertain when their outcome cannot be established.

Phase 1: implement the contract and measure the unchanged router using a fake broker.
Phase 2: wake the C# outbox immediately, move CSV/UI work out of dispatch, preserve
SQLite durable event and attempt commits, and warm account connections before arming.
Phase 3: consider versioned, bounded-freshness instrument/preflight caches with
explicit invalidation on account/route/session change. A stale or missing cache
uses the current verified read path or holds the action; count this as a target
miss. Edit/cancel/close may need fresh broker reads and must not guess position state.
Schedule background reads around eligible writes within the existing aggregate
broker budget; changing broker pacing requires independently verified limits.
Do not describe calling an SDK method before it waits on the limiter as API transfer.

## Measurement and acceptance gates

Use receiver monotonic time for: complete message arrival, decode/validate end,
queue admission, worker start, event commit, preflight end, attempt commit,
rate-limit permit, HTTP transport header-write start, body-write completion and
response completion. Instrument actual HTTP transport writes (or a verified transport
trace hook), not just entry to _send or client.request. Record connection reuse and
DNS/TCP/TLS setup separately. Transport write start does not prove remote receipt.

Correlate measurements with event_id/trade_id and action; omit credentials and raw
HTTP headers. Report p50/p95/p99/max and percentage under 10 ms for all attempted
writes. Separate warm/idle, bursts, cold connection, expired session, rate-limited,
preflight read and queue-blocked cases, but never silently exclude slow samples.
Held observations have no outbound-write latency and must be counted separately.
Sender Stopwatch timing and receiver monotonic timing are separate clock domains;
never subtract them without a clock synchronization method.

Under 10 ms is initially an observed warm-path target, not a dispatch TTL. A timing
miss is measured and explained; do not silently drop or retry lifecycle actions
because they crossed 10 ms. Existing event freshness and safety holds still apply.

Acceptance tests must prove: wrong token/path/protocol rejection; sender machine
binding; malformed/fragmented/oversized frames; duplicates via WS and HTTP; lost ACK;
restart before/after dispatch claim; no write replay for uncertain results; ordering
of create/edit/cancel/close; partial fills and ambiguous position holds; queue and
slow-client limits; stop/disarm while queued; idle wakeup; and a real C#-to-Python
loopback test with a fake Aqua transport. Benchmark while broker polling and dashboard
are active as well as idle. No live trades are part of transport validation.

Only after interoperability and tests pass: version application packages 0.5.0,
keep event schema 1.1.0 unless a deliberate contract change is necessary, document
measured limits, and build a credential-free handoff. Do not deploy the C# observer
or enable API trading as part of writing this design.

## API references for implementation

- Microsoft ClientWebSocket concurrency contract:
  https://learn.microsoft.com/en-us/dotnet/api/system.net.websockets.clientwebsocket?view=net-10.0
- Python websockets server/handshake options (use the locally installed version):
  https://websockets.readthedocs.io/en/stable/reference/sync/server.html
