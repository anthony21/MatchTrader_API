# Live raw signal receiver

Run the v3-base dashboard, then configure a strategy sender on this same machine:

| Sender transport | Endpoint |
| --- | --- |
| WebSocket | `ws://127.0.0.1:8766/signals` |
| HTTP POST | `http://127.0.0.1:8765/signals` |
| Existing native capture HTTP sender | `http://127.0.0.1:8765/capture/events` |

No bearer token, password, or authentication message is required for signal
ingress. The bridge token environment setting has been removed. Broker login
tokens and the local dashboard control session are separate and unchanged.
These are loopback endpoints; senders run on the same computer as this app.

B21/R01 senders that treat the setting as a base URL append `/api/hcamm/events`.
The dashboard accepts both `/api/hcamm/events` and `/signals/api/hcamm/events`
without a signal token, so the existing `http://127.0.0.1:8765/signals` setting
also works with that sender convention. Batches are preserved as one raw message
with individual parse results attached. Some B21 versions stop
publishing after HTTP 401/403; restart that sender after correcting the receiver.

Update: [the parsing engine](PARSING_ENGINE.md) now adds individual R01 source
models and named order shapes to each new raw journal record's `signals` array.
The HTTP batch and exact original message remain available together.

Send one UTF-8 message per WebSocket frame/message, or one HTTP request body.
JSON objects can contain any fields. Example:

```json
{"event_id":"r01-example-1","source":"R01","kind":"ENTRY","symbol":"XAUUSD","account_id":"source-account","price":4340}
```

The original text is preserved. JSON fields are parsed when available; plain text
or unparseable JSON is still displayed as raw text. `source`, `strategy`, or
`sending_source` labels the sender; `kind`, `event_type`, `eventType`, or `type`
labels the event. Unknown/nested fields remain available in the raw payload.
If the sender doesn't provide a source field, use `/signals?source=R01` or
`/signals?source=StrategyManager` (supported on HTTP and WebSocket).

After journaling, the sender receives JSON with `status: received`, a local
numeric `id`, the sender's `event_id` when supplied, and a `parsed` flag. HTTP
returns 202. An acknowledgement means local receipt, not a broker order or fill.
Each message is limited to 64 KiB. Every received message is recorded, including
sender retries; this feed does not deduplicate or execute trade instructions.

Trading bridge subscribes to `ws://127.0.0.1:8766/events`, gets a snapshot of the
latest 200 records, then receives pushed updates. It provides source/type/search
filters and expandable raw messages. It reconnects after interruptions. Slow
subscribers receive a replacement snapshot rather than blocking strategy senders.
The latest 2,000 records are retained in `data/dashboard/signals.sqlite3`.

Reception runs for the lifetime of the application, independently of the page,
broker connections, selected account, and old Start/Stop capture state. This
dashboard's `/events` and `/capture/events` HTTP paths are compatibility aliases
for the same observation-only raw receiver. They no longer dispatch copying.
The old typed capture/copy implementation remains in the source but is not invoked
by these signal endpoints. Historical dashboard/copying instructions are superseded
for this raw signal page.

Use `--signal-port` to change the WebSocket port (default 8766); the dashboard
receives its actual port from the local status API. The Quantower outbox source
now sends without Authorization; older installed senders that still attach a
header also work because the receiver doesn't require or validate it.

The listener and browser delivery are verified with local test senders. A sender
must support the selected transport: an HTTP-only strategy cannot use a `ws://`
URL just by changing its scheme. No running strategy or relay configuration is
automatically redirected. Point its supported sender at the appropriate endpoint.

Validation: 249 Python tests and 18 frontend tests passed, plus actual local
WebSocket/HTTP-to-browser delivery without credentials. The C# outbox source was
updated to omit Authorization; its build could not be rerun because this shell's
.NET installation contains no SDK. No installed Quantower DLL was replaced.

## Trading bridge table

The live card now expands each message batch into individual event rows. Sender
buttons select All, R01, P01, P02, X17, or another observed source. r01Auto and
r01Local share the R01 lane; their event kind is shown beneath the lane label.
Explicit source prefixes determine the lane. Legacy chain events with an
`x17-spine` detail prefix appear under X17; panel events with a P01RR_ label appear
under P01. Unidentified senders retain their own source button.

Columns: Lane, Machine ID, Side, Entry, Stop loss, Take profit, Ladder grade,
Timestamp (UTC). The symbol appears beneath machineId. long/short display as
BUY/SELL, and ladderGrade supplies the grade. Parsed source/order shapes supply
the rows; older or unsupported events use their raw payload fields.

Machine and event-type dropdowns plus text search narrow the selected lane.
Click the lane's plus button to view the event payload and original batch.
Prices display up to eight decimal places, with the original value available
on hover and in the payload. Empty/zero levels display a dash. Timestamps display
the sender's UTC time to milliseconds; exact timestamps remain available on hover.
The table scrolls horizontally on small screens.

Table validation: 22 frontend tests passed and the production build succeeded.
Browser verification used actual received R01 events for row values, filters,
payload expansion, navigation replay, and desktop/mobile layouts.

The **Filter columns** funnel button sits in the first table header, alongside the
column names. Its dropdown first lists groups; clicking a group opens its field
checkboxes, with All groups returning to the first level. It exposes all 43 schema
fields plus the derived Lane column. The original eight columns are selected by
default. Groups and fields are searchable; Select all and Restore defaults are available.
Selections persist in this browser across navigation and reloads. At least one
column remains selected. Optional fields display false, zero, null, and structured
instrument metadata explicitly; long values have full-text hover titles.

The header button remains visible during table scrolling. The dropdown fits the
viewport, closes on Escape/outside click, and restores button focus on Escape.

Column-picker validation: 28 frontend tests passed, including a catalog check
against all fields in SIGNAL_SCHEMA.json. Browser checks verified selection,
defaults, persistence, all 44 columns, group navigation, keyboard dismissal,
scrolling, and responsive layout using the live feed.
