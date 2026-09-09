# Vue dashboard and shadow bridge

## Run on Windows

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.venv/Scripts/python -m matchtrader.dashboard.cli
```

Open http://127.0.0.1:8765. Node runs for build/test only; Python serves the compiled
Vue assets and local API. There is no continuously running Node development server.
The dashboard starts stopped and does not connect to a broker automatically.

Environment entries (keep actual values in `.env`):

```dotenv
MTR_ACCOUNT_ID=YOUR_TRADING_ACCOUNT_ID
MTR_ACCOUNT_IDS=OPTIONAL_SECOND_ID,OPTIONAL_THIRD_ID
MTR_R01_LEDGER=C:/path/to/R01_TRADES.csv
MTR_BRIDGE_TOKEN=YOUR_RANDOM_LOCAL_SENDER_SECRET_AT_LEAST_32_CHARACTERS
```

`MTR_ACCOUNT_IDS` supplies optional choices before authentication. Successful login
replaces the choices with verified account IDs from the broker. Other logins or
brokers require separate configurations/instances. One account is selected at a time.
This dashboard does not fan out a source order to multiple accounts.

## Controls

- **Connect account:** executes the documented existing-user login using credentials
  stored on the backend. Does not register a new user. See `FIRST_CONNECTION.md`.
- **Start shadow bridge:** begins reading the configured ledger at its current EOF
  and enables the authenticated `/events` receiver. No trading requests are made.
- **Stop & disconnect:** rejects subsequent events, stops observation and releases
  the SDK connection. The dashboard process remains available. Broker orders and
  positions are not cancelled or closed.
- **Refresh orders:** reads active pending orders through the selected account's SDK.
  It is manual, separately timestamped, and never inferred from the incoming feed.
- **Account selector:** requires capture stopped before switching. Each account has
  a separate persistent journal. A configured account is not labeled verified until login.

The incoming table refreshes every 1.5 seconds and shows the latest 200 records from
the selected journal. Hover over an event to see its source label and hold reason.
This is local polling, not a claimed broker WebSocket integration. Source timestamps
are preserved; bridge receipt timestamps are UTC. Receipt is not broker arrival.

## Feed semantics

`observation`: a fresh R01 CSV row (including intent, regrade, cancelled or touched).
These rows lack volume and a verified outbound contract. They are never promoted to
broker orders. `touched` means a source observation, not a broker fill.

`preview`: a complete authenticated event generated a MARKET, LIMIT, or STOP request
shape. It has not been submitted. Explicit lots, SL and TP are required; zero means
an unset bracket. Symbol rules and live connectivity still require verification.

`held`: wrong account, stale/future timestamp, repeated creation, stale revision,
invalid bracket direction, unsupported STOP_LIMIT, or edit/cancel without a verified
broker mapping. There are no synthetic broker IDs or simulated broker acceptances.

## Sender contract

POST JSON to `http://127.0.0.1:8765/events` with
`Authorization: Bearer <MTR_BRIDGE_TOKEN>`. HTTP 202 acknowledges local capture only.
The receiver requires **Start shadow bridge**. This is our versioned contract, not
the unverified existing TradingBox payload. Do not redirect R01's shared relay
configuration until its sender has been adapted.

```json
{
  "schema_version": 1,
  "source_machine": "machine-example",
  "strategy_instance": "r01-instance-example",
  "event_id": "unique-event-id",
  "source_order_id": "stable-order-id",
  "revision": 1,
  "emitted_at": "REPLACE_WITH_CURRENT_ISO8601_UTC_TIMESTAMP",
  "account_id": "REPLACE_WITH_SELECTED_ACCOUNT_ID",
  "action": "CREATE",
  "instrument": "XAUUSD",
  "side": "SELL",
  "order_type": "LIMIT",
  "volume_lots": "0.01",
  "price": "2400",
  "sl_price": "2410",
  "tp_price": "2380"
}
```

Values above illustrate syntax, not sizing or price recommendations. Default event
age limit is 30 seconds, with five seconds of future clock tolerance. Every changed
state requires a new event ID and higher revision. Duplicates are persisted across
restarts. This deduplication protects shadow capture; it does not provide a live
execution journal, recovery, fill reconciliation, or exactly-once trading.

Standalone tools: `python -m matchtrader.bridge.cli serve` starts a shadow-only
receiver without the dashboard; `python -m matchtrader.bridge.cli observe --ledger
PATH --seconds 30` captures a bounded interval. Do not run two receivers on port 8765.

## Docker

```text
docker compose --profile dashboard up --build dashboard
```

The image builds Vue in a Node stage and serves its static output with Python.
Runtime is limited to 384 MiB and half a CPU in Compose; build stages may use more.
Only host loopback port 8765 is published. The source ledger folder is mounted
read-only and data journals are mounted writable. Set `MTR_LEDGER_DIRECTORY` in the
Compose environment to the host ledger directory (default `../../trials`). Inside
the container, the source path is `/source/R01_TRADES.csv`. Configure volume ownership
for container UID 10001 on Linux. Docker is not installed on the current Windows VM,
so this container path is supplied but has not been run here.

## Security and operation

The local control API requires a per-process session token and same-origin/Host
checks. Sender authentication is separate. Broker passwords and tokens never enter
Vue state, static assets, logs, or browser storage. Keep this service on loopback;
it is not an internet-facing multi-user dashboard. Anyone controlling this Windows
user session can access the local controls.

One controller owns the selected-account SDK lease and shadow journal. Source
observation runs in a background thread that stops on truncation/rotation errors.
Start resumes from the new EOF; it never replays the gap while stopped. Journals are
local SQLite files under `data/dashboard`; retention/archiving is a future operational
task for long-running installations. Closing the terminal process also stops capture.

## Verification

Run `npm --prefix frontend test` for Vue unit tests and
`python -m pytest` for Python modules. With Google Chrome installed, run
`npx playwright test` from `frontend/` after building Vue. That browser test starts
an isolated backend on port 8766 with temporary test accounts and a temporary ledger;
it does not load your `.env` or contact a broker. Unit tests likewise block broker
network access. Browser test artifacts contain test data only and are excluded
from the handoff.
