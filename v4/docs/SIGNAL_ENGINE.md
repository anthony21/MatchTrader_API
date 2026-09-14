# Signal engine

How an incoming trade signal becomes a broker order, in three steps and no more:

```
incoming signal  ->  SignalEngine.decide()  ->  OrderPlan  ->  BrokerDispatcher.send()
```

Module: `matchtrader/signals/`. The dashboard's `signal_copy.py` is the caller: it receives,
records, asks the engine, and hands the plan to the dispatcher.

## Shapes: one base, one subclass per sender (`signals/shapes.py`)

`BaseSignal` carries what every intent needs to become an order: `clientEventId`,
`machineId`, `source`, `kind`, `label`, `timestampUtc` (timezone required, normalised to
UTC), `symbol`, `side` (long/short/0/1 normalised to BUY/SELL), `entry`, `stopLoss`,
`takeProfit`, and the sender's own order type when it states one. `scope` is the identity a
cancel must share with its intent.

The differences define the subclasses, chosen by `source`:

| Source | Shape | What it adds |
| --- | --- | --- |
| `P01_LOG`, `panel` | `P01Signal` | Recognises the tool's lifecycle labels: `P01RR_HHmmss_n` and `L:<edge>@<wall>@<bar>` (`M:` for mirrored). A `panel` intent must carry `P01RR_`. |
| `chain` | `ChainSignal` | `detail`; `from_x17` when it starts with `x17-spine`. A lane with `x17_only` refuses anything else. |
| `R01` | `R01Signal` | `grade`, `stamp`, `rfx`, `arm`, `detail`; the order type is read from the detail text (`resting limit at range edge` is LIMIT, the two beyond-edge details are STOP). |

Attribution rules live on the shape (`check_attribution(lane)`), not in the engine.

## Symbol map (`signals/symbols.py`)

A plain table keyed by the incoming symbol: destination symbol, lots, order handling
(`SOURCE`, `ENTRY`, `MARKET`, `LIMIT`, `STOP`). Stored in `data/dashboard/relay/symbol-map.json`,
separate from the lane settings, so it is looked up rather than re-declared, and can later be
replaced from an external source. Routes: `GET /api/symbol-map`, `POST /api/symbol-map`
(full replacement). The dashboard's **Symbol map** page edits this table on its own; the
Strategy signal lane form on Copy settings no longer carries symbols. Settings files saved
before the split still load: their symbols are moved into the map on first start.

## Lane settings (`SignalSettings` in `dashboard/signal_copy.py`)

What the operator means: `machine_id`, `source`, `destination_account`, optional
`connection_name`, the P01 log switch, additional sources, and `x17_only`. Persisted without
symbols in `signal-copy-settings.json`.

## Engine (`signals/engine.py`)

`SignalEngine(lane, symbols).decide(signal, context)` returns an `OrderPlan` or raises
`Refusal(reason)`. Every check is here, in this order: armed; destination connected and
verified unless paper; machine and source match the lane; chart connection when the lane
names one; freshness (not before arming, within 30 s, 5 s future tolerance); no bridge
request already sent for the lifecycle; a label; the shape's attribution; no ended
lifecycle in the same batch or recorded later; no prior broker attempt for the scoped
lifecycle; a symbol mapping; a side and positive prices; brackets on the correct side;
order type from the map, the sender, or a fresh destination quote for `ENTRY`; and, before
a live write only, the destination's own instrument limits (lot minimum, maximum, step,
close-only, long-only) read from the broker.

`OrderPlan` is the exact broker call: `instrument`, `side`, `order_type`, `volume`, `price`,
`sl`, `tp`, plus `label` and `scope`. `plan.request()` is the keyword arguments;
`plan.method` is `open_position` or `create_pending_order`.

`Context` is the facts outside the signal: mode, arming, now, destination, the API owner,
and what the store already holds for this lifecycle.

## Dispatcher (`signals/dispatch.py`)

`BrokerDispatcher.send(plan, api)` and `.cancel(request, api)` perform the broker call and
nothing else, returning `Outcome(decision, request, response, reason)`. `accepted` only when
the broker returned an identity (or `OK` for a cancel); any exception or unrecognised reply
is `uncertain`. The request and reply are appended to the capture raw log when the owner has
one.

## What `signal_copy.py` still owns

Receiving batches, deduplication by machine plus client event id, the durable record of
every signal and its decision, the Paper/Live gate (a paper plan is recorded, never sent),
the `dispatching` commit before a live write, and unwinding: a cancel or close of exposure
this owner created is never gated by arming, freshness or the master switch.
