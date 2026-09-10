# Incoming trades — release 0.3.0

The first React workspace replaces both incoming activity tables. The existing
Vue application mounts `IncomingTrades.jsx` through `NativeEvents.vue`; login,
Orders and Copy settings continue using their existing control plane. No broker
credentials enter React and filtering never changes copy routing.

The table separates local time, instrument/side, source account, strategy source,
event kind, action, opening evidence, quantity/unit, entry/fill price, stop loss,
take profit, result and the rightmost persistent Trade ID. Scroll horizontally
for additional columns on smaller screens. Details expand source order, position,
execution and request IDs, original action attribution and the receiver reason.
Decimal strings retain their supplied precision. Missing brackets display a dash.

Source account selection supports multiple accounts, scoped by machine and
connection as well as account ID. Empty selection means all. Strategy tabs,
event-type selection and search combine with the account filter. Filters apply
to the latest 200 native and 200 legacy events, not the entire journal. Legacy
CSV observations have no source account when their records do not establish it.

## Backend meanings, version 1.0.0

Authenticated `GET /api/event-meanings` returns the event/action/source catalog.
Each event from `/api/capture/events` and `/api/events` includes additive `meaning`
metadata: `version`, `event`, `action`, `source`, `action_source`, `opened`, `result`.
Codes and descriptions are defined in `capture/meaning.py`. Unknown codes retain
their original value and receive an explicit unrecognized-code description.
The native event wire schema remains 1.1.0 and mapping schema remains 1.0.0.

R01/X17 attribution uses the persistent linked trade origin where known; an edit
from MANUAL does not overwrite its original strategy label. `action_source`
preserves the current event's attribution. Empty SendingSource is never treated
as manual or used to guess a strategy. R01 CSV provenance is labeled R01 but is
observation-only. The extension/strategy must supply actual attribution for
unlinked native events; the frontend cannot recover missing strategy provenance.

| Opening state | Meaning |
| --- | --- |
| confirmed | Non-snapshot FILL, execution ID, positive quantity, explicit OPEN effect |
| closing | Same execution evidence with CLOSE effect; may be a partial close |
| fill_unknown | Execution exists but opening/closing effect is unknown |
| snapshot | Existing source inventory; no new opening inferred |
| observed / removed | Position lifecycle observation; no new opening inferred |
| unconfirmed | This event does not establish a new source opening |

These are source-event facts, not Aqua execution confirmation. Accepted requests
and POSITION observations alone do not establish new openings. Old extensions
that omit fill_effect display “Fill · effect unknown.” The opening metric counts
events, including partial opening fills, rather than unique open positions.
The Orders workspace remains the broker-side view and persistent ID mapping view.

## Validation

Dedicated tests cover semantic mappings, fill evidence, persisted origin versus
action source, authenticated catalog access, frontend precision, lifecycle columns,
combined account/strategy/type/search filters, and unchanged copy preconditions.
Chrome checks exercise the built React view on desktop and mobile using explicit
test fixtures, alongside the real local settings and capture APIs. They do not
claim live broker execution or complete strategy attribution from old extensions.


## Live push (0.4.0)

The native Quantower feed now uses authenticated `GET /api/capture/stream` over
SSE. The frontend sends the same-origin session token in an HTTP header, never
in a URL. Same-origin/Host checks and session authentication apply before the
stream opens. This is a local dashboard transport, not a broker WebSocket adapter.
The existing SDK WebSocket client still requires a verified broker protocol.

Committed event insertion and decision changes wake stream readers immediately.
There is no fixed native-event polling delay while the stream is live. Each
connection starts with the latest 200-event journal snapshot. Subsequent snapshots
replace it, preserving updated decisions and avoiding duplicate rows. Slow readers
coalesce to the latest bounded snapshot. Socket writes occur outside journal locks;
eight stream slots and write timeouts bound slow/disconnected clients. Idle streams
send a heartbeat every ten seconds without querying SQLite. Store/server shutdown
wakes readers. Restart revisions are ephemeral; reconnect always resynchronizes.

The UI batches received snapshots onto the next browser animation frame. This is
not a 10 ms or hard real-time guarantee. Disk commits, scheduling, browser work,
and transport affect latency. A browser-only test measured 115–375 ms from starting
a synthetic POST through DOM rendering on this Windows environment. It blocked
native polling and verified push, then reloaded to check snapshot recovery.
These measurements do not establish Quantower-to-Aqua execution latency.

The badge shows Live push or reconnecting/polling fallback. Reconnection backs off
from one to ten seconds; missing heartbeats abort the connection after 25 seconds.
When push is unavailable, the existing 1.5-second native poll is the recovery path.
Legacy CSV/control status still refresh at 1.5 seconds; Orders still use five-second
broker snapshots. The C# sender and trade routing were not changed by this release.

Validation: 258 Python tests, 29 frontend tests, six Chrome end-to-end checks,
production build and Ruff. Tests cover authenticated streaming on loopback,
commit/decision wakeups, replay, shutdown, fragmented chunks, heartbeat loss,
reconnection, disposal, native polling suppression and browser delivery.
