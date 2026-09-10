> v4 adds [P01/manual copying settings and Strategy Manager logs](MANUAL_COPYING.md).

# Quantower capture and order lifecycle (v4)

Application **0.2.0** adds [explicit trade mappings and partial execution evidence](TRADE_MAPPING.md).
Use the versioned event schema in that document for the new C# publisher. Existing
version-1 events remain accepted; no extension deployment is included in this change.

The Windows C# extension observes native Quantower requests, results, orders,
fills and positions. It persists an outbox and posts to Python's authenticated
`/capture/events`. Python assigns one UUID trade ID per machine, connection,
source account and source order ID. Each observation has its own event ID.
Fills link source order IDs to source position IDs. Native quantity is preserved;
it is not assumed to mean Aqua lots.

The **Orders** workspace button opens current pending orders and open positions.
Both snapshots refresh every five seconds while that page is open. Their times
are shown separately. The bridge page separates native C# events from old CSV
observations; the latter are never executable.

## Persistence and recovery

`data/dashboard/quantower/trades.csv` contains the latest 1,000 trade records by
default; `--csv-limit N` changes that limit. `capture.sqlite3` is authoritative.
It retains identities, events and dispatch attempts after CSV entries roll off.
Do not delete this database to clear the display: doing so loses deduplication.
Back it up using SQLite's backup API while the service is running, or copy it
with its WAL after shutdown. Event/database retention is separate from CSV retention.
An Excel lock can delay CSV replacement; the UI reports this and the next event retries.

A CREATE can be attempted once per trade ID, even if its event ID changes.
Edit/cancel/close attempts are keyed by native request ID. Dispatch intent is
committed before the broker request. Timeout, malformed success, or a crash
around dispatch leaves the trade **uncertain**. No automatic mutation retry occurs.
This is conservative duplicate prevention, not a claim of exactly-once broker execution.
Closed IDs remain tombstones rather than being reused.

Successful cancellation/full close marks the ID resolved. Exact linked position
history can resolve SL/TP closures during 15-second background reconciliation
while a configured route is capturing, and when the Orders page refreshes; that lookup
covers seven days. Partial history, missing positions without closure evidence,
and unknown IDs remain unresolved. An uncopied native cancellation/removal can
resolve its source-only record. Partial fills share the order trade ID; multiple
orders merged into one source position are ambiguous and cannot be closed by guessing.

## Install the C# observer

The installed Quantower 1.146.18 uses .NET 10. Build against its actual BusinessLayer:

```powershell
dotnet build quantower/HCAMM.QuantowerCapture -c Release -p:QuantowerBin=C:/Quantower/TradingPlatform/v1.146.18/bin
dotnet run --project quantower/HCAMM.QuantowerCapture.Tests -c Release
```

Copy `HCAMM.QuantowerCapture.dll` from its `bin/Release/net10.0-windows` folder to
`C:/Quantower/Settings/Scripts/Strategies/HCAMM.QuantowerCapture/`.
Do not distribute Quantower's proprietary BusinessLayer DLL with the handoff.
In Quantower Strategies manager, add **HCAMM Quantower Capture v3**, select its
configuration file and start that observer. Leave the user's trading strategies
unchanged. Only one capture instance may run in a process.

Default configuration path:
`%LOCALAPPDATA%/HCAMM/QuantowerCapture/capture.json`.

```json
{
  "endpoint": "http://127.0.0.1:8765/capture/events",
  "token": "REPLACE_WITH_LOCAL_MTR_BRIDGE_TOKEN",
  "outbox": "C:/Users/Administrator/AppData/Local/HCAMM/QuantowerCapture/outbox",
  "max_pending": 10000,
  "sources": {"HCAMM:R01": "R01", "HCAMM:X17": "X17", "OE": "MANUAL", "Multiple OE": "MANUAL", "Modify Position screen": "MANUAL", "Close Position Screen": "MANUAL"}
}
```

The private token must match `.env`'s `MTR_BRIDGE_TOKEN`. No Aqua tokens go into
the extension. Restrict configuration/outbox access to the Windows user.
Start dashboard capture before the observer. Its startup inventory is marked
`snapshot`; snapshots never submit trades. A stopped/unavailable receiver leaves
events in the outbox. Events older than 30 seconds are captured but held rather
than traded later. Disk failure or a full outbox is a capture fault: stop copying
and inspect Quantower's strategy log and delivery metric. The outbox is durable
after the local disk write; no callback mechanism can recover an event lost before persistence.

## Configure copying

Use the **Copy settings** sidebar page. Alternatively, pass a private route file with
`--route data/quantower-route.json` to the dashboard.
The service starts disarmed on every launch. Connect the explicitly chosen demo
destination, start capture, then use **Allow API trading**. **Stop API trading** stops new
dispatch; it does not undo an already submitted request or close existing orders.
`Stop & disconnect` also disarms. A real-money destination cannot be armed by this bridge.

Example structure (replace the source identities and sizing after inspecting native events):

```json
{
  "machine": "SOURCE_MACHINE",
  "connection_id": "EXACT_QUANTOWER_CONNECTION_ID",
  "account_id": "EXACT_QUANTOWER_ACCOUNT_ID",
  "destination_account": "123456",
  "sources": ["MANUAL", "R01", "X17"],
  "exclusive_destination": true,
  "legacy_route_disabled": true,
  "symbols": {
    "EURUSD": {
      "destination": "EURUSD",
      "quantity_multiplier": "REPLACE_WITH_VERIFIED_LOTS_PER_SOURCE_UNIT",
      "max_lots": "REPLACE_WITH_APPROVED_LIMIT",
      "same_price_scale": true
    }
  }
}
```

The booleans acknowledge an exclusive destination for this route and that the
old relay is not also copying these same source events there. They do not change
TradingBox or Quantower settings automatically. Source connection/account,
source tags, symbol, quantity multiplier and maximum lots are mandatory. Futures
contracts and FX lots need a deliberate conversion, and prices must use the same
scale. The bridge validates current destination volume limits before dispatch.

Native successful CREATE results can produce MARKET/LIMIT/STOP requests. EDIT,
CANCEL and full/partial CLOSE use stored broker IDs, never a symbol/price search.
Unsupported stop-limit/trailing orders, offset SL/TP, missing broker IDs, absent
pending orders and ambiguous netted positions are held with a reason. Market
and filled-pending position management requires an explicit `positionId` from a
response or `orderId` relationship on an open position. If Aqua omits that link,
the mapping needs further broker-contract work; do not infer it from matching prices.

## R01, X17 and manual attribution

`SendingSource` is captured verbatim. `sources` maps **exact observed values** to
MANUAL/R01/X17. An untagged order remains UNKNOWN; do not map an empty source to
manual because an untagged strategy can send it too. You may explicitly include
UNKNOWN in a route only if copying all otherwise-matched account events is intended.
Trade origin persists while each event retains its action source, so a manual
edit does not rewrite a known R01 origin.

The installed R01/X17 DLLs expose B21 message types but no public global event
subscription was found. Their internal signals and direct HTTP relay messages are
not native Quantower orders. For editable strategy code, set `SendingSource` on
native order requests and call `CapturePublisher.PublishSignal(CaptureEvent)` for
R01/X17 signal observations. This requires the strategy source and a shared loaded
capture assembly; simply installing the observer does not instrument those binaries.

The C# observer must run inside awake Quantower on Windows. Python/Vue can use
the existing Docker setup; Docker does not make Quantower run while its VM sleeps.

## Validation boundary

Offline tests cover IDs across restarts/CSV rollover, duplicate creates, wrong
accounts/sizing, uncertain writes, mapped modifications/cancellation/close, HTTP
authentication, Vue navigation and outbox acknowledgements. Compiling against the
installed DLL verifies the native API surface. These checks do not establish a
live end-to-end copied trade. That needs a configured source/sizing, positive source
attribution and a controlled source-order test, including fill/position identity.

References: [Quantower Core](https://api.quantower.com/docs/TradingPlatform.BusinessLayer.Core.html),
[request parameters](https://api.quantower.com/docs/TradingPlatform.BusinessLayer.RequestParameters.html),
[Match-Trader Platform API](https://app.theneo.io/match-trade/platform-api/).


Application 0.5.0 implements the native [Quantower WebSocket receiver](QUANTOWER_WEBSOCKET_RECEIVER.md).
The C# extension remains a separate sender deployment.
