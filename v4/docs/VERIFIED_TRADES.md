# Verified trades

This is the record of every trade the copier has handled for an AquaFunded account,
and the document to reach for when one of those records has to be defended. It
describes what the code does, not what it is meant to do. Where the code has a known
gap, the gap is stated here in the same terms the code uses. Modules:
`capture/verified.py`, `capture/mapping.py`, `capture/store.py`, `capture/reconcile.py`,
`capture/manual_send.py`, `capture/pamm_publisher.py`, `core/reason.py`,
`dashboard/copy_controls.py`, `dashboard/ledger_view.py`; pages `VerifiedTrades.vue`,
`PaperTrades.vue`, `CopyControls.vue`, `TradeSend.vue`.

Throughout, a **send attempt**, a **broker acceptance** and a **broker read-back** are
three different facts. The ledger records all three separately and only the third can
make a trade verified.

## The verification predicate

`capture/verified.py` is a read-only classifier over one `MappingLedger.snapshot()`
dict. It never touches the database and never causes a write. Its module docstring
states the rule:

> A write response (an accepted order, a created position) only proves the broker
> accepted the request. It can never satisfy `verified`: that requires a later,
> independent read-back - an open position or a closed-history row carrying the
> broker's own native id and its own open time - matched against the snapshot's
> symbol and side.

The rows that may contribute are selected by this filter, quoted from `classify()`:

```python
READ_BACK_READERS = frozenset({"open_positions", "closed_positions"})
...
rows = [r for r in snapshot["destination_observations"]
        if r["position_id"] == destination_link["native_id"]
        and r["symbol"] == snapshot["symbol"] and r["side"] == snapshot["side"]
        and r.get("reader") in READ_BACK_READERS
        and r.get("scope") == expected_scope]
```

and the predicate itself is one line:

```python
verified = bool(destination_link) and bool(row) and has_time and has_source and not guarded
```

Read literally: a trade is verified only when

1. a destination position id is linked to the trade (`destination_link`);
2. a broker **read** - the `open_positions` or `closed_positions` reader - returned
   that exact position id, with the snapshot's symbol and side, for the same broker
   and account (`scope`);
3. that read carried AquaFunded's own open time: a non-blank `open_time` string or a
   non-null `open_time_millis` (`has_time`);
4. a source identity was linked (`has_source`); and
5. no split/merge guard applies (`not guarded`).

A broker write response can never satisfy this. That is structural, not a convention
observed at call sites:

- The write response model, `models/operation.py` `Operation`, carries `status`,
  `nativeCode`, `errorMessage`, `orderId` and `positionId`. It has no timestamp field
  of any kind, so condition 3 cannot be met from it.
- The only writer of `destination_observations` is `MappingLedger.observe_destination`,
  and its only callers are `CaptureStore.observe_positions` (reader `open_positions`)
  and `CaptureStore.observe_closed` (reader `closed_positions`). Both are called from
  `capture/reconcile.py` with the results of `api.open_positions()` and
  `api.closed_positions()`. The dispatch paths (`capture/router.py`,
  `capture/manual_send.py`) record the broker's ids on the `trades` row and in
  `action_history`; they write nothing to `destination_observations`.
- Even a row someone wired into that table from a write response would be excluded by
  the `reader` and `scope` checks above.

Tests: `tests/capture/test_verified.py::test_write_response_alone_never_verifies`,
`::test_a_dispatch_response_cannot_populate_destination_observations`,
`::test_write_response_reader_never_verifies_even_with_matching_fields_and_time`,
`::test_mismatched_scope_never_verifies`, `::test_blank_open_time_without_millis_is_not_verified`.

### When read-back runs

Read-back is not continuous. `reconcile()` runs on every open-positions refresh
(`controller.refresh_positions`, which the shell requests every five seconds only while
connected with orders or positions outstanding, and on opening the Orders page) and, in
the capture worker, every 15 seconds while capture is running, an account is connected
and a native route is configured. It matches open positions by exact
`broker_position_id` or `broker_order_id`, then symbol and side. Only trades whose
position id is absent from the open snapshot and whose order is no longer pending are
looked up in closed history, over the last seven days. Closure is decided from the sum
of `closed_positions` row volumes against the destination's requested quantity, never
from the trade row's `state`.

## States

`classify()` returns exactly one of the following; `ledger_view.verified_row()` adds
`paper_sent`. **Only `verified_open` and `verified_closed` may be described as
verified.** No other state may, whatever else the row carries.

| State | Meaning |
| --- | --- |
| `candidate` | No destination position id has been linked and the trade is not in flight. The default. Eligible for an explicit send only if the trade row is still `observed`, its source is enabled, an ACCEPTED CREATE signal is on record and it has never been sent in either mode (see *Copy controls*). |
| `paper_sent` | A `paper_sends` row exists for the trade and it is not verified. Set by `ledger_view`, not `classify()`. The paper path never touches the broker, so the trade owns no destination identity and cannot become verified. Listed on the Paper trades page; the Verified trades table hides it and says how many it hid. |
| `sent_unconfirmed` | A destination position id was recorded (from a write response, or by legacy migration) but no qualifying read-back row exists. This is the state of a freshly accepted live send. It asserts acceptance, not arrival. |
| `read_back_no_time` | A read-back row matched the position id, symbol, side and scope but carried neither `open_time` nor `open_time_millis`. The broker confirmed the position; it did not report its open time. Not verified. |
| `verified_open` | The predicate holds. The `closed_positions` rows for this position do not sum to the destination's requested quantity, or none exist. If a `closed_positions` row exists, or the trade row is `resolved`, the row carries the reason *"Closure is not confirmed by a broker read; the position may have closed without read-back evidence."* |
| `verified_closed` | The predicate holds **and** `closed_positions` rows for this position sum to at least the destination's requested quantity. Requires a parseable destination requested quantity; otherwise the trade stays `verified_open`. |
| `guarded` | More than one destination position is linked to the trade, or a linked destination position has more than one contributing trade. Broker evidence cannot be attributed to this trade; an explicit allocation would be required. Not verified even when a timed read-back exists. |
| `unattributed` | No source identity was ever linked. Not verified even when a timed read-back exists. |
| `uncertain` | No destination position id, and the trade row is `uncertain` or `dispatching`: a write attempt was committed and its outcome is not known, or the broker refused it. Never retried automatically. |
| `cancelled`, `rejected` | **Display labels only.** `VerifiedTrades.vue` knows how to render these two labels, but neither `classify()` nor `ledger_view` ever emits them as a `state`. A cancellation or rejection is carried in the row's `cancellation` field (the *Reason · origin* column) alongside whichever state the classifier produced: a source order that ended before any send is `candidate` with origin `source`; a broker-refused write is `uncertain` with origin `broker`. |

The row also carries `reasons`, the classifier's sentences followed by the mapping
ledger's own (`Destination identity not confirmed`, guard messages), and
`mapping_status` (`confirmed`, `incomplete` or `uncertain`). These explain the state;
they do not alter it.

## Two clocks

Every timestamp on the record page comes from one of two clocks and is labelled with
it. They are never merged into one column because they are asserted by different
parties and neither is corrected to the other: a single "time" column would hide who
said when.

| Field | Clock | Source |
| --- | --- | --- |
| `timestamps.sent_at` | local | `action_history.updated_at` of the CREATE attempt: when this process last recorded the attempt's state (claimed, then accepted or uncertain). Not the instant bytes left the wire. |
| `timestamps.confirmed_at` | local | `destination_observations.first_seen_at`: when this process first stored the read-back row. |
| `timestamps.broker_open`, `broker_open_millis` | **broker** | `openTime` / `openTimeMillis` as returned by AquaFunded on the read. `broker_open` is the broker's ISO string or `null`, never fabricated from the millis; a blank or whitespace-only string is returned as `null` and never blocks the millis value. |
| `pamm.published_at` | local | When the TradingBox publication attempt was reserved. |
| Paper `decided_at` | local | When the paper request was recorded. |
| `cancellation.at` | local | When the outcome reason was recorded. |

The page formats both clocks in the browser's timezone via `localTime()`; the label
under each heading (*local clock* / *broker clock*) says whose instant is being
formatted. A broker string without a timezone designator is shown as
*timezone unavailable* rather than assumed.

Clock evidence is protected on write: `observe_destination` fills `open_time` and
`open_time_millis` only when the column is still empty (`COALESCE`), so a later read
without a time, or a local clock rollback, can never remove a broker timestamp once
recorded. Mutable fields (volume, close time) are updated only when the new
observation is at least as recent as the stored one.

## Reason origins

When a write attempt does not end in a recorded acceptance, `core/reason.py` builds a
reason and `CaptureStore.record_reason` persists it to `outcome_reasons`. The rule,
enforced at that one write site, is that **an error must always give somewhere to
investigate and must never read as a bare unknown**: a reason without a non-empty
`origin`, `code` and `evidence` is refused with `ValueError`. The four origins assert
different things:

| Origin | Asserts | Built from |
| --- | --- | --- |
| `broker` | The broker answered the write and refused it, or answered without OK. | Only `status`, `errorMessage` and `nativeCode` from the response body; every other field is dropped before it can reach a summary or log. `code` is the native code when it looks like a code, else `HTTP <status>`. |
| `local` | The broker replied; a check our own code imposes failed afterwards (unrecognised status, missing broker identity, unreadable JSON, persistence failure), or the process restarted mid-attempt (`InterruptedProcessing`). | The exception type and our own message. Never confused with a wire failure. |
| `transport` | The failure is known to be on the wire: a transport exception, or no response received. The outcome is unconfirmed - not accepted, not refused. | Exception type, HTTP status when one exists, scrubbed message; evidence names what to reconcile against. |
| `unconfirmed` | The phase could not be established at all: no structured evidence of wire, broker or local cause. | Exception type and scrubbed message. Used when an exception carries no structured `.reason`. |

`ledger_view` adds a fifth, synthetic origin `source` for a trade whose source order
was Cancelled, Refused or Removed before any destination position existed; its
evidence is the native ORDER/POSITION event.

Every recorded outcome from a failed or unconfirmed attempt is `uncertain`; the trade
row becomes `uncertain` and the attempt is closed so it is never retried. The page
renders the latest reason's summary, or when the summary is empty composes
`<code> · <origin> · no message supplied` so that something investigable is still
shown. Summaries are capped at 200 characters after scrubbing (see *Limitations*).

## Copy controls

`dashboard/copy_controls.py` persists one `CopyControls` object at
`data/dashboard/copy-controls.json`: a `mode` of `paper` or `live` and a switch for
each of the three governed sources, `P01`, `X17` and `MANUAL`. The default - and what a
missing file resolves to - is **paper with every source off**. Any other attribution
(R01, UNKNOWN, a typo) is never eligible, whatever the file says.

Enabling a source makes that source's captured trades **eligible** and shows them as
candidates. It never sends anything. A trade reaches the broker only through the
explicit send action on a candidate row (`POST /api/trades/send`, `manual_send.send`),
and only while the master switch is on `live`. Nothing sends on arrival, on a timer, or
when the stream replaces a row. Lot size is the only editable field; instrument, side,
order type, entry and brackets come from the captured ACCEPTED CREATE signal, with an
optional route translating the symbol spelling and nothing else.

Before anything is written or sent, in both modes: the trade must exist, its source
must be enabled, it must still be `observed` and classify as `candidate`, have no
destination order or position id, belong to no other destination, never have been
sent before in either mode, have an ACCEPTED CREATE signal on record with absolute
brackets, an order type of MARKET, LIMIT or STOP, a side, and a finite positive volume.

- **Paper** records the exact request that would have gone to `paper_sends` and stops.
  It never touches the API, so it can never produce a broker identity or a read-back row
  and is therefore incapable of reading as verified
  (`test_paper_send_is_structurally_incapable_of_verification`).
- **Live** additionally requires `MTR_ENABLE_WRITES=true` for the dashboard process and
  a connected destination whose account matches the selected one. The instrument is
  validated against the broker before any write; a preflight read failure is a refusal
  naming the exception class, with nothing claimed. The attempt is then committed
  (`attempts`, `action_history`) **before** the network write, so a crash leaves it
  `uncertain` and never retryable, and a duplicate click or second operator is refused
  by the primary key. A successful response yields `sent_unconfirmed`, not verified.

A trade is sent at most once in either mode: a paper record or a durable attempt
refuses every later send. The Live switch in the UI requires a second confirming click.

## TradingBox / PAMM: a third viewpoint only

`capture/pamm_publisher.py` tells TradingBox about a trade only after the broker
read-back has verified it - Aqua, then verify, then publish, never simultaneously.
`publish()` returns without acting unless `classify()` reports `verified_open` or
`verified_closed`, no `pamm_publications` row already exists for the trade, and the
TradingBox forwarder is enabled **and** live with a configured URL and key. Transport is
the forwarder's own send against its validated URL and authentication header; there is
no second HTTP path.

The attempt row is inserted before the wire, then updated with the upstream status,
duration and exception class. Only a 2xx integer status counts as published; anything
else is an attempt, and the row itself blocks any automatic retry. TradingBox's answer
is written to `pamm_publications` and nothing else happens: a failed publication never
touches the trade, its evidence or its classification
(`test_a_failed_publication_never_changes_a_real_verified_trade`), and the controller
records only a status message. TradingBox is never read to confirm or invalidate a
trade. The *PAMM* column reports *Not published* or *Published (local time) ·
TradingBox (status)*.

## Where the records live

`data/dashboard/quantower/capture.sqlite3`, mapping schema 1.1.0. Relevant tables:
`trades`, `attempts`, `action_history` (requests and outcomes),
`destination_observations` (read-back evidence, one row per open position or per
closing execution), `outcome_reasons`, `paper_sends`, `pamm_publications`. The
dashboard builds the Verified trades and Paper trades sections from the same 200-row
`mapping_view()` pass as the mappings page and pushes them over `/api/stream` only when
their content changes; nothing on the pages is derived from the clock at build time, so
unchanged evidence is never resent.

## Limitations

Stated so they can be checked, not argued around.

- **Resolved trades are not revisited.** `reconcile()` selects
  `state NOT IN ('observed','resolved')`. A trade that reached `resolved` because a
  CLOSE write response succeeded, with no closed-history read-back yet, is never looked
  up in closed history again and stays `verified_open` indefinitely even if it did
  close. The row carries the *Closure is not confirmed by a broker read* reason.
  Widening the selection is a behaviour change outside `verified.py`.
- **Identical closes can collapse.** A closing execution row is keyed by the broker's
  `uid`, else `closingOrderID`, else `<position id>@<close time>:<normalised volume>`.
  Two closes of identical size at an identical timestamp with neither broker execution
  id collapse to one row. This under-counts closed volume, so it can only fail to claim
  `verified_closed`; it can never falsely claim it.
- **`verified_closed` needs a requested quantity.** The closed-volume comparison uses
  the destination's requested quantity (`lots`). When that is absent or unparseable the
  trade cannot reach `verified_closed`.
- **Read-back has a cadence and a window.** See *When read-back runs*. Closed history
  is read over the last seven days only; the 15-second pass requires a configured
  native route. Between passes a row lags the broker.
- **Credential scrubbing is defense in depth, not a proof.** The primary control on
  broker messages is the field allowlist (`status`, `errorMessage`, `nativeCode`); a
  structured `errorMessage` is dropped rather than stringified. The regex scrub for
  key/value secrets, auth schemes, 12+ digit runs and e-mail addresses runs on the
  allowlisted text and on exception messages, before the 200-character cut. It catches
  the patterns it was written for and nothing more.
- **The journal schema bump is forward-only.** Opening a 1.0.0 journal bumps it to
  1.1.0 in place; older code refuses a 1.1.0 journal with *Unsupported mapping journal
  schema version*. There is no downgrade path. Back up `capture.sqlite3` (and its
  `-wal`/`-shm` files, if present) before the first run of this release.
- **`cancelled` and `rejected` are labels, not states.** See *States*. A trade whose
  source order ended before any send is still classified `candidate`, so the page offers
  its Send control; the server refuses the send with *Trade is not a candidate (state
  resolved, candidate)* and that refusal is what the operator sees.
- **Copy-controls fallback covers a missing file.** A missing `copy-controls.json`
  resolves to paper with every source off. A present but invalid file raises at load
  rather than silently falling back; `test_defaults_are_paper_with_every_source_off`
  covers only the missing case.
- **The view is bounded.** Sections are built from the 200 most recently updated trades
  and the 200 most recent paper sends for the selected account. Older records remain in
  SQLite and are not shown.
- **Verified is not a fill report.** `verified_open` says the broker returned the
  position on a read with its own open time. It says nothing about price, slippage or
  whether the broker's volume equals what was requested beyond what the *Evidence*
  section shows.
