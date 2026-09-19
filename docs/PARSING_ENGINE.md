# Signal parsing engine

`matchtrader.signal_parsing` contains the application-owned parser and shapes.

## R01Signal

The source model contains all 43 fields in the owner's supplied payload, using
the same names. All fields are required. It supports r01Auto and r01Local, any
nonempty kind, and preserves additional fields. Instrument metadata may be null
or an object so populated metadata can be retained when received.

Strings, booleans, and integer fields use strict types. Prices, volume, and stamp
are finite Decimals. Parsing raw JSON reads decimal numbers directly as Decimal.
timestampUtc retains its original string and fractional-second precision and is
validated to include a timezone. Empty strings and zero values are retained.
grade remains in the source record; application projections use ladderGrade.

## R01OrderShape

The r01OrderShape projection is produced for source=r01Auto, kind=intent. Other
events retain their full source model and can receive additional projections later.

| Shape field | Source |
| --- | --- |
| instrument | symbol |
| orderSide | side: long -> BUY, short -> SELL |
| type | orderType uppercased: LIMIT, STOP, MARKET |
| price | entry for LIMIT/STOP; null for MARKET |
| slPrice | stopLoss |
| tpPrice | takeProfit |
| isMobile | false |

Unsupported order types/directions and invalid prices produce shape-specific
issues while keeping the valid original source model. Prices remain as received;
destination precision and symbol mapping belong to later request preparation.

The enclosing parse result retains machineId, clientEventId, label, boxInstanceId,
ladderGrade, ladderArm, and broker references through its `signal` property.
An order shape accepts explicit destination symbol and volume when converted into
an existing SDK request model. Source volume is retained only on the source model.

```python
from decimal import Decimal
from matchtrader.signal_parsing import default_engine

results = default_engine().parse_raw(raw_message)
for result in results:
    if result.status == "parsed" and "r01OrderShape" in result.shapes:
        signal = result.signal
        order = result.shapes["r01OrderShape"]
        # Values below come from this machine's copy settings and symbol mapping.
        request = order.to_request(volume=Decimal("0.2"), instrument="BTCUSD")
        payload = request.wire()
```

`to_request()` returns CreatePendingOrderRequest for LIMIT/STOP and
OpenPositionRequest for MARKET. It constructs a model; operations can consume it
later through the established API. Destination symbol and volume are both required.

## Registry and results

Each source registers its full model and named shape builders:

```python
engine.register("future-source", FutureSignal, shapes={"futureShape": build_shape})
```

Builders return a shape or None for events they do not project. Duplicate source
registration is rejected. P01/X17 definitions can be registered after their formats
are defined. Unknown sources receive status=unsupported with their raw message
retained by intake.

The engine accepts an object or array. Each array item gets an independent result:
index, status (parsed/invalid/unsupported), model, signal, shapes, and issues.
Source-model errors mark that item invalid. Shape errors leave status=parsed and
are recorded under the shape name in issues. Later valid items still parse.

## Live intake

Both HTTP and WebSocket feed SignalHub. Every new journal record now includes a
`signals` array of parse results, committed alongside the exact raw request and
existing payload. Subscribers receive that same record through live push and
snapshots. Each result's index identifies the item in its raw request batch.
Earlier journal records retain their original format and can be parsed from raw
when needed. The Trading bridge raw-message view continues to show the source.

Serialized derived records use strings for Decimal values to retain precision.
SDK request.wire() emits numeric JSON fields. Use the retained raw text with
parse_raw() when reprocessing source events.

Validation: 278 Python tests passed, including mixed-batch isolation, complete
source preservation, strict types, exact decimal/timestamp handling, projections,
SDK request conversion, and journal/live-push persistence. A read-only replay of
658 retained R01 events produced 190 order shapes with zero parse/shape issues;
those events included heartbeat, intent, cancelled, refused, touched, and closed.
