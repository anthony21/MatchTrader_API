# Trade mapping contract — application 0.2.0

The workspace remains `v4/`. Release versions use `major.minor.patch`: major for
breaking contracts, minor for compatible capabilities, patch for compatible fixes.
Event schema **1.1.0** and mapping schema **1.0.0** are versioned independently
(release 1.0.0 moves the mapping journal schema to **1.1.0**, forward-only; see
[verified trades](VERIFIED_TRADES.md)).
The receiver accepts legacy integer `1` and string `1.0.0` events as well.
The stable HTTP User-Agent remains `hcamm-matchtrader/0.1.0` for broker compatibility;
it is not a release-version indicator. `/api/status` exposes the release and schema versions.

## Handoff to the C# extension session

POST one JSON object to `http://127.0.0.1:8765/capture/events`, with
`Content-Type: application/json` and `Authorization: Bearer <MTR_BRIDGE_TOKEN>`.
Capture must be started. See `schemas/capture-event-1.1.0.json` for the complete
machine-readable contract. Broker credentials remain in the Python backend.

Example partial execution (replace identities, sizing and timestamp):

```json
{
  "schema_version": "1.1.0",
  "event_id": "unique-observation-id",
  "machine": "quantower-machine",
  "connection_id": "exact-connection-id",
  "account_id": "exact-source-account-id",
  "order_id": "qt-order-42",
  "position_id": "qt-position-17",
  "execution_id": "qt-execution-101",
  "request_id": "original-native-request-id",
  "emitted_at": "2026-09-10T02:00:00Z",
  "kind": "FILL",
  "action": "OBSERVE",
  "source": "MANUAL",
  "symbol": "EURUSD",
  "side": "BUY",
  "order_type": "LIMIT",
  "quantity": "0.4",
  "quantity_unit": "native",
  "price": "1.15",
  "fill_effect": "OPEN",
  "order_quantity": "1.0",
  "cumulative_filled_quantity": "0.4",
  "remaining_quantity": "0.6",
  "position_quantity": "0.4"
}
```

`quantity` on a FILL is the **incremental execution quantity**, not cumulative
filled quantity or whole-position volume. `execution_id` is the stable native
execution identifier, preserved across redelivery. An event ID identifies an
observation; it must not be reused for different data. Execution deduplication
uses machine/connection/account plus execution ID, even when the event ID changes.
Conflicting execution data is rejected and its journal transaction is rolled back.

Set `fill_effect` to OPEN or CLOSE only when the native API establishes that fact.
Otherwise send UNKNOWN. The optional totals are source-reported snapshots; omit
unknown values rather than sending zero. `position_quantity` is the whole position,
which may include other trades. It is not an allocation to this order. For a split,
send each execution with its own position ID. For a merge, retain each contributing
order and execution ID while using the shared position ID.

The receiver keeps exact native units and explicit conversion to destination lots.
It does not equate futures contracts, a risk percentage, or cash risk with lots.
Timestamps must contain UTC/offset information and are normalized to UTC in the
journal; the dashboard displays local time.

Accepted source CREATE events remain the copying trigger. FILL, ORDER, POSITION,
REQUEST and snapshot events update observation evidence and never create a second
broker trade. EDIT/CANCEL/CLOSE events still require native request IDs, attribution,
an explicit route, verified demo destination and armed copying.

An HTTP 202 response acknowledges local processing. Read `status` and `reason` to
distinguish captured, held, accepted, uncertain and duplicate outcomes. An accepted
broker request is not proof of a fill. The acknowledgement includes separate
`broker_order_id` and `broker_position_id` when known; neither substitutes for the other.

## Persistent broker mapping

The existing `trades` table retains stable UUIDs and dispatch tombstones. Additional
tables preserve all identity links, execution fills, quantity observations, whole
position observations and action history. Source links are scoped by machine,
connection and account; destination links are scoped by broker origin and account.
The journal is bound to one broker origin and rejects reuse for another broker.
Each link carries evidence and a timestamp. Many source/destination position links
can belong to one trade, and one position can link to several contributing trades.

Existing single-ID columns remain for compatible, unambiguous dispatch. Multiple
source positions never overwrite one another. Position-only broker responses leave
the order ID empty. Older journals where position IDs may have been substituted
as order IDs migrate to an uncertain state instead of treating that guess as confirmed.
Migration preserves trade UUIDs, event deduplication and action tombstones. Older
execution history is not silently reconstructed into fill totals.

The action journal records the exact mapped request before submission, its source
request ID, broker/account, returned IDs and accepted/uncertain result. A crash
during dispatch changes the pending attempt to uncertain on restart; it is not retried.
The broker response is represented by its validated outcome and identifiers; raw
responses, credentials and cookies are not stored in the UI action record.

## Orders interface

The **Trade mappings** section of Orders uses the authenticated
`GET /api/trade-mappings` endpoint for the selected destination plus unassigned source
trades. It displays confirmed/incomplete/uncertain identity mappings, separate
Quantower and broker IDs, reported partial quantities, recorded executions,
position contributors and action history. Confirmed means the displayed IDs have
evidence; it does not promise complete fill reconciliation or matching P/L.

Source/destination units stay separate. Recorded opening/closing contributions
are evidence totals, not a guarantee that all executions were observed. Whole-position
volume is shown separately. Allocation remains unconfirmed until an explicit,
complete allocation mechanism exists; no manual confirmation button fabricates it.

## Current execution boundaries

One configured destination is still dispatched per source trade. The normalized
records are account-scoped, but this release does not enable multi-account fanout.
Unambiguous partial closes use the exact broker position ID and converted quantity.
Cancelling a pending remainder does not resolve its known filled position. Closing
a position does not resolve a still-pending remainder.

Automatic actions on split/merged positions are held for allocation. This release
represents their relationships; it does not distribute a close quantity or bracket
edit among contributors. Explicit broker order-to-position relationships populate
destination position snapshots. No broker execution IDs are invented from position
snapshots or a successful CREATE response. A future broker execution adapter can
populate the destination fill ledger when stable execution evidence is available.
Source fill support is active now; destination execution totals may remain unknown.

Tests cover the new modules and changed behavior with offline broker fakes. No live
order submission or live Quantower-to-Aqua copied trade is established by these tests.
The C# source and installed strategies are owned by the other session and unchanged here.

## Release validation

Release 0.2.0 passed 240 Python tests (including the module-to-test-file check),
20 frontend tests, 4 Chrome browser tests, Ruff, the frontend build and Poetry metadata
validation. The populated split/merge, deduplication, migration and crash-recovery
scenarios used isolated test journals and fake brokers. The local dashboard restarted
on 0.2.0, logged in successfully and served the authenticated mapping endpoint.
Its native journal was empty; a SQLite backup, integrity check and before/after
identity/event/attempt comparison passed. Capture and copying remained disabled.
