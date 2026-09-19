# Shared signal schema — draft 1

The sampled R01 feed contains 87 events with exactly the same 43 fields in every
event. The HTTP body is an array of these event objects. This draft preserves the
sender's camelCase field names and values. The machine-readable definition is
[SIGNAL_SCHEMA.json](SIGNAL_SCHEMA.json).

Sample: 2026-09-18, machine `nasdaq_30s`, symbol `BTCUSD`. Counts describe a fixed
local snapshot; the feed continues to grow.

| kind | source | Count | Observed content |
| --- | --- | ---: | --- |
| heartbeat | r01Auto | 13 | Status text in detail, account/connection identity, zero price fields |
| intent | r01Auto | 24 | Lifecycle label, direction, entry/stop/target, range and grade context |
| cancelled | r01Auto | 23 | Lifecycle label, direction, prices, cancellation explanation in detail |
| refused | r01Local | 24 | Lifecycle/range references, account/connection identity, refusal reason in detail |
| touched | r01Auto | 3 | Lifecycle label, direction, prices, touch quote text in detail |

## All shared fields

Descriptions identify field roles; opaque strategy codes retain their sender-defined meanings.

| Group | Fields | JSON type | Treatment |
| --- | --- | --- | --- |
| Identity | machineId, robotName, source | string | Machine, robot label, publishing source |
| Account | accountId, connectionName | string | Preserve identifiers as strings, including empty values |
| Event | clientEventId, refClientEventId | string | Event identifier and sender-provided reference |
| Event | kind, mode | string | Event type and sender mode |
| Time | timestampUtc | string (date-time) | Sender timestamp, preserving fractional-second precision |
| Ordering | sequence | integer | Sender sequence; retain with machine/source context |
| Lifecycle | label, brokerOrderId, brokerPositionId | string | Lifecycle label and supplied broker references |
| Range | rangeKind, wallId, boxInstanceId | string | Sender range and box references |
| Range | wasBeyond | boolean | Sender beyond flag |
| Trade | symbol, side, orderType | string | Instrument symbol, direction, order type |
| Trade | entry, stopLoss, takeProfit, volume | number | Preserve supplied numeric values; use decimal parsing for calculations |
| Grade | ladderGrade, grade, ladderArm | string | Separate sender fields; preserve each independently |
| Grade | stamp | number | Numeric strategy context |
| L2 | l2Class, l2Word, l2ChurnBand | string | Opaque strategy context |
| L2 | l2DbandDigit, l2BirthRank | integer | Integer strategy context |
| L2 | l2PosInWin | boolean | Sender flag |
| Context | tapHash, tier, cell, rfx | string | Opaque strategy context |
| Context | inverted, dryRun | boolean | Preserve the value on each event |
| Detail | detail | string | Status/reason/context text; keep original text intact |
| Instrument metadata | instrument | null (observed) | Every sampled value is null; define its populated shape when observed |

Totals: 30 strings, 5 numbers, 3 integers, 4 booleans, 1 null field.

## Contract decisions

- Use one shared event model; `kind` selects the event-specific interpretation.
- This observed wire schema requires all 43 fields because every sampled event
  contains them. Unknown additional fields remain accepted for future senders.
- Keep source, kind, mode, side, and orderType as extensible strings. Observed
  examples are recorded in the JSON schema; they are not exhaustive enums.
- Preserve empty strings, zero, false, and null exactly. Field presence and
  meaningful population are separate: heartbeat/refused prices are zero, and
  accountId/connectionName are empty in sampled intent/cancelled/touched events.
- Preserve `grade` and `ladderGrade` separately: grade is empty throughout this
  sample while ladderGrade is populated on many intents and cancellations.
- Keep `dryRun` event-scoped: sampled heartbeat/refused events have true;
  intent/cancelled/touched events have false.
- Store receiver metadata separately: receivedAt, local message ID, batch index,
  and original raw request text. Each array item becomes one event with a reference
  to its containing raw message. This is the proposed structure for later parsing.
- Keep timestampUtc and receivedAt separate. Keep sequence as supplied; this
  snapshot does not establish uniqueness across sender restarts.

The draft's required fields and primitive types were checked against all 87
sampled events. The implemented R01Signal model and projections are documented
in [PARSING_ENGINE.md](PARSING_ENGINE.md).

## Owner's parsing-engine requirements (2026-09-18)

- Copy settings displays `machineId` as the selectable **Source**. Each R01
  strategy instance should publish a distinct machineId so its strategy information
  can be selected independently.
- Preserve the wire `source` separately. `r01Auto` identifies strategy signals;
  the owner identifies `r01Local` as the strategy's errors/warnings. Associate both
  with their machineId.
- Preserve `symbol` for instrument identification and copying.
- Preserve `ladderGrade` as a primary input for selecting grades to act on and
  measuring which grades perform best. The owner subsequently clarified that
  `grade` is ignored by application parsing and decisions; `ladderGrade` is the
  authoritative grade. The raw payload still retains every received field.
- Preserve `ladderArm` for later trade-outcome grouping and win-percentage analysis.
  Retain the exact source value, including any grade text and separators.
- Normalize direction for broker requests: `long` -> `BUY`, `short` -> `SELL`.
  Preserve the original side in the received event.
- Destination volume comes from copy settings. Keep the received `volume` as source
  data; copy sizing uses the configured destination volume.
- Capture broker-returned `brokerOrderId` and `brokerPositionId` when available
  and append/link them to the corresponding trade lifecycle for tracking.
  Implementation detail to preserve provenance: original source fields remain in
  the raw event; copied execution references are associated with their destination
  broker/account so multiple copies can each retain their own identifiers.

Follow-up observation: 312 received R01 events through 2026-09-18 23:06:52 UTC.
ladderArm and ladderGrade are populated in 166; side in 176; machineId and symbol
in all 312. grade, brokerOrderId, and brokerPositionId are empty throughout this
sample, and volume is always zero. These are observations, not field restrictions.

## Mapping to the established pending-order request

Use the unchanged SDK's `create_pending_order()` request model:

| Received/configured value | Broker request field | Transformation |
| --- | --- | --- |
| symbol plus destination symbol mapping | instrument | Use the broker's instrument identifier |
| side | orderSide | long -> BUY; short -> SELL |
| orderType | type | limit -> LIMIT; stop -> STOP |
| entry | price | Numeric price, aligned with destination instrument precision |
| stopLoss | slPrice | Numeric stop price |
| takeProfit | tpPrice | Numeric target price |
| Copy settings destination sizing | volume | Configured destination lots |
| Application default | isMobile | false |

Endpoint: POST `/mtr-api/{SYSTEM_UUID}/pending-order/create`. The session manager
provides the selected destination broker/account context and authentication.
machineId, ladderGrade, ladderArm, and lifecycle references stay in application
routing/tracking records associated with the request. The returned orderId is
linked as the destination brokerOrderId; a resulting position ID is linked when
available. A market order uses `open_position()` with no price or type field.
