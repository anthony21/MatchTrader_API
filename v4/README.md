> v4: See [manual copying and P01 setup](docs/MANUAL_COPYING.md). Copy settings are now available in the Vue sidebar; copying starts off.

# Match-Trader Python client

Current release: **0.9.1**. Use **Choose broker login** to select a named .env profile,
log in, then choose one of its returned trading accounts. See [broker login setup](docs/BROKER_PROFILES.md).
Start with the [installation guide](docs/SETUP.md). See [trade mappings and the C# event contract](docs/TRADE_MAPPING.md)
for separate source/broker IDs, partial fills, split/merged positions and schema versions.

This is the **v4 application iteration**. Run all commands from this folder.
See [versioning](docs/VERSIONING.md) for its layout and next-iteration workflow.

An importable Python library for broker-hosted Match-Trader Platform API installations, including AquaFunded **when that broker grants API access and supplies the correct Match-Trader terminal/account credentials**. No AquaFunded URL, account, cookie protocol, or streaming subscription is guessed.

The implementation covers all **19 documented REST endpoints**, a separate optional WebSocket transport, typed data objects, pandas DataFrames, NumPy closing-operation statistics, a read-only CLI, and Docker. A local **Vue dashboard and shadow event receiver** now provide account selection, start/stop controls, and an incoming activity table. The original `/events` receiver remains preview-only. The new native `/capture/events` receiver supports explicitly configured demo-account copying. It does not connect to unrelated non-Match-Trader APIs.

See [Quantower capture and routing](docs/QUANTOWER_CAPTURE.md) for trade IDs, the bounded CSV, C# installation, source attribution and remaining live-validation requirements. The **Orders** sidebar page shows pending orders and open positions.

## Vue dashboard

From this project folder, after installing the Python dependencies:

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
poetry run python -m matchtrader.dashboard.cli
```

Open **http://127.0.0.1:8765**. Select an account and use **Connect account** to log in and discover other accounts. **Start capture** records new R01 ledger observations and accepts authenticated events; **Stop & disconnect** stops capture and closes the SDK connection. The dashboard remains available to restart capture. It starts stopped with copying disarmed. Native copying additionally needs saved Copy settings (or an explicit route file), a verified demo account and the Allow API trading control; `.env` alone cannot arm it.

Set `MTR_R01_LEDGER` to your local `R01_TRADES.csv` path to watch new strategy activity. The frontend displays observations, request previews, held events, and an independently refreshed broker pending-order snapshot. No historic ledger replay or invented lot sizes. See [dashboard setup](docs/DASHBOARD.md), [registration and first connection](docs/FIRST_CONNECTION.md), and [routing status](docs/DIRECT_ROUTING.md).

## First-time setup

1. Obtain an active Match-Trader account from your broker. Ask whether Platform API access is enabled for that account and allowed by its terms. Use the broker-supplied **Match-Trader terminal URL** and credentials; a marketing-site URL or client-office login may not be the same.
2. Obtain the trading account ID if you have multiple accounts. Ask for a separate trading API origin if required. The client can discover `partnerId` (login `brokerId`) through platform details and `SYSTEM_UUID` through login. You do not need to register a new account through this SDK if one already exists.
3. Copy `.env.example` to `.env` inside this folder. Fill in `MTR_PLATFORM_URL`, `MTR_EMAIL`, `MTR_PASSWORD`, and, when applicable, `MTR_ACCOUNT_ID`. Keep `.env` local. Do not paste passwords or tokens into chat, commit them, or include them in reports. Environment variables override `.env`.
4. Start with `platform`, then `balance`. These are read operations. A 401 may mean incorrect credentials, expired session, missing permissions, or the broker's cookie convention; it does not establish which one. Current docs conflict about `co-auth`: `MTR_COOKIE_MODE=session` uses the session token; `account` uses `tradingAccountToken.token`. Confirm with the broker if the first read fails.
5. If your broker requires MFA, another authentication exchange, or a private streaming protocol, obtain that contract. This SDK implements the published password/one-time-token flows, not an invented MFA bypass.

No credentials are needed to install the library or run its tests. Unit tests use mocked connections. Standalone Aqua login, balance, active orders, open positions and refresh returned HTTP 200 after configuring the shared SDK User-Agent. History, populated order/position responses and the broker-specific WebSocket flow remain separate live validation work. See [first connection](docs/FIRST_CONNECTION.md).

### AI handoff and trade comparison

Read [agent.md](agent.md), or ask another AI to read it. [AGENTS.md](AGENTS.md) points automatically discovered repository instructions to the same handoff. The portable [operations skill](.agents/skills/matchtrader-operations/SKILL.md) covers connection diagnosis, browser history export, account isolation, and evidence-based reconciliation.

Create a source bundle with `poetry run python scripts/build_handoff.py --output dist/matchtrader-v4-handoff.zip`. It includes source, tests, skills, docs, dependency locks, and Docker files; it excludes local credentials and account data. The recipient supplies their own `.env` and browser/tool access. This is a source handoff, not an installer that grants broker access.

To reconcile an existing broker CSV with R01 records, run:

```powershell
poetry run python scripts/reconcile_r01.py --ledger /path/to/R01_TRADES.csv --broker /path/to/CLOSED_POSITIONS.csv --output data/comparison --start 2026-09-08T00:00:00Z --end 2026-09-09T00:00:00Z --account ACCOUNT_ID
```

Replace the window with the actual export bounds. Optional `--verdicts /path/to/PMM_VERDICTS.csv` and `--slogs /path/to/ScriptsData` preserve relay and Strategy Manager evidence. The command generates a filterable HTML table, complete CSV, alternative candidates, unmatched intents, source snapshots and summary. It treats level matches as candidates and leaves unobserved send/receipt times blank. It does not silently assign a timezone to a broker export.

### Local Python installation (Windows PowerShell)

Requires Python 3.12 or later and [Poetry 2.2 or later (2.x)](https://python-poetry.org/docs/#installation). From the `v4` folder:

```powershell
poetry install
Copy-Item .env.example .env
# Edit .env locally before running the next commands.
poetry run matchtrader platform
poetry run matchtrader balance
```

Poetry creates the project environment in `.venv` and installs the versions in
`poetry.lock`. The same `poetry` commands work on Linux/macOS; use
`cp .env.example .env` to create the credentials file.

Use `poetry add <package>` to add a runtime dependency or
`poetry add --group test <package>` for test tools. After editing dependency
constraints manually, run `poetry lock`. Commit `pyproject.toml` and `poetry.lock`
together. Use `poetry sync --with test` to synchronize a development environment.

### Docker

Install Docker Engine with Compose support, or a supported Docker Desktop installation. The current Windows development machine does not have Docker installed; container build/run validation remains outstanding. On a Windows Server host, use a supported Linux container host/VM instead of assuming Docker Desktop is supported.

```powershell
Copy-Item .env.example .env
# Fill .env locally. Do not repeat Copy-Item over a populated credentials file.
New-Item -ItemType Directory -Force data
docker compose build client
docker compose run --rm client platform
docker compose run --rm client balance
docker compose run --rm client snapshot --symbols XAUUSD --from 2026-09-07T00:00:00Z --to 2026-09-08T00:00:00Z
docker compose --profile test run --build --rm tests
```

Only run the test service in an offline unit-test environment; it has no broker credentials and Compose disables its network. For testing without any `.env` file, use `docker build --target test -t matchtrader-tests .` then `docker run --rm --network none matchtrader-tests`.

The runtime container is non-root, has a read-only root filesystem, limits CPU to one core and memory to 512 MB, and sets NumPy BLAS threads to one. Results are written to the `./data` mount. On Linux, ensure that mount is writable by container UID 10001. Docker isolates and limits resource consumption; it does not inherently make Python faster or reduce memory use. Large histories may need shorter date windows or adjusted limits. The CLI exits and closes its connection after each command; it is not an idle background daemon.

## Python usage: one public API facade

```python
from matchtrader import MatchTraderAPI, Settings

settings = Settings.from_env('.env')
with MatchTraderAPI(settings) as api:
    # Login is automatic on the first trading read; api.login() is also available.
    balance = api.balance()
    quotes = api.quotes(symbols='XAUUSD,EURUSD')
    instruments = api.instruments()
    orders = api.active_orders()
    positions = api.open_positions()
    closed = api.closed_positions(
        from_='2026-09-07T00:00:00Z',
        to='2026-09-08T00:00:00Z',
    )
    candles = api.candles(
        symbol='XAUUSD', interval='M15',
        from_='2026-09-07T00:00:00Z',
        to='2026-09-08T00:00:00Z',
    )
    frame = api.dataframe(closed, numeric=['openPrice', 'closePrice', 'volume', 'netProfit'])
    frame.to_csv('closed-operations.csv', index=False)
    # If the broker returns timezone-less dates, explicitly supply its confirmed timezone.
    stats = api.analyze_closed_operations(closed, naive_timezone='UTC')
# REST pool and any socket owned by this facade are released here, even after an exception.
```

The example timezone `UTC` is only appropriate after the broker confirms it. No timezone is silently assigned by the analysis layer. `from_` is the Python spelling of the API field `from`. Numeric response values are stored as `Decimal`; conversion to floating-point is explicit in the pandas analysis path. Unknown broker response fields are preserved; unexpected request fields are rejected.

For full signatures, see [endpoint inventory](docs/ENDPOINTS.md) and `models/*_request.py`. Every operation accepts a request model, dictionary, or keyword fields. For example:

```python
from matchtrader.models.candles_request import CandlesRequest

request = CandlesRequest(symbol='EURUSD', interval='M15',
                         from_='2026-09-07T00:00:00Z', to='2026-09-08T00:00:00Z')
with MatchTraderAPI(settings) as api:
    candles = api.candles(request)
```

Mutation endpoints exist but require `MTR_ENABLE_WRITES=true`. Registration is also a write. Use only broker-supported order types and instrument constraints. A sell limit's request fields are `orderSide='SELL'` and `type='LIMIT'`. Pending creation uses `price`, editing uses `priceOrder`, reading uses `activationPrice`. Unset SL/TP serialize as zero. Full close uses `positionId` and string volume; partial close uses numeric volume. `edit_pending_order()` returns the raw response because the current docs omit its success schema.

The client does not automatically retry mutations. A transport timeout or unreadable mutation response raises `UnknownOutcomeError`; reconcile broker state before resubmission. A 401 during a safe read causes at most one refresh and retry. The connection refreshes the session after its documented 15-minute lifetime and caps refresh attempts at four per rolling hour. The refresh cookie is retained by HTTPX; broker-specific trading-account-token renewal is not inferred from the session refresh endpoint.

## Multiple accounts

Use an explicit account client instead of changing a global current account:

```python
import pandas as pd
from matchtrader import MatchTraderAPI, Settings

with MatchTraderAPI(Settings.from_env()) as broker:
    with broker.for_account('ACCOUNT_1') as first, broker.for_account('ACCOUNT_2') as second:
        first_balance = first.balance()
        second_balance = second.balance()
        combined = pd.concat([
            first.account_dataframe(first.open_positions()),
            second.account_dataframe(second.open_positions()),
        ], ignore_index=True)
```

Replace ACCOUNT_1/ACCOUNT_2 with the actual Match-Trader trading account IDs, not challenge names. Both IDs must be returned by that login. Each account independently selects its tokens and system UUID from its login response and owns its own HTTP cookie jar, refresh state and optional socket. Each handle supports all 19 endpoint methods. `account_dataframe()` adds `mtr_account_id` and `mtr_platform_url` so combined analysis retains provenance. Keep different currencies separate when calculating P&L totals.

`MTR_ACCOUNT_ID` still selects the default account for CLI commands and direct facade calls; it may be omitted if you only use explicit `for_account()` handles. Separate login credentials or brokers can use separate `Settings.from_env('account-a.env')` / `Settings.from_env('account-b.env')` files and independent `MatchTraderAPI` contexts. Environment variables override either file. Keep those credential files outside version control.

`for_account()` defaults to the parent's login and trading API origin. For a different API origin, supply `trading_url='https://broker-confirmed-origin.example'`. Account-specific system UUID and WebSocket URL, protocol and headers are cleared when creating a different account handle; supply broker-confirmed per-account overrides when needed. For example `broker.for_account('ACCOUNT_2', ws_url=..., ws_headers_json=...)`. A child owns its own lease and must be closed independently, even if its parent closes first. No automatic trade copying or broadcasting is performed.

Multiple accounts are verified with mocked server responses, including different tokens, system UUIDs and refresh cookies. Actual concurrent-login behavior remains subject to the broker's session policy.

## Optional persistent WebSocket

REST is pooled HTTP. WebSocket is an **independent secondary transport**, not a way to send every REST endpoint over a socket. Published Platform API docs do not provide a current URL, authentication handshake, subscription frames or execution-event schema. Obtain these from your broker before setting `MTR_WS_URL`, optional `MTR_WS_SUBPROTOCOL` and `MTR_WS_HEADERS_JSON`.

```python
with MatchTraderAPI(Settings.from_env()) as api:
    stream = api.websocket()  # Opens only when explicitly requested.
    # Send the exact text/bytes/JSON frame prescribed by your broker:
    stream.send(broker_subscription_frame)
    while True:
        frame = stream.receive(timeout=30)
        process(frame)
```

The two variables/functions above represent your broker-specific adapter and application; they are not built-in subscription examples. The transport sends heartbeat pings, limits message size and its receive queue, and closes with the facade. Only one reader may consume the shared socket at a time. Multiple readers need an application dispatcher. On disconnection it surfaces the underlying `websockets` exception; reconnect/resubscription and token renewal must follow the broker's contract. Authentication headers are explicit and are not automatically copied from REST to a potentially unrelated host.

## Architecture and singleton ownership

```text
src/matchtrader/
  api.py                  public MatchTraderAPI facade
  cli.py                  read-only executable adapter
  core/
    base_service.py       service base; borrows the owner's connection
    base_connection.py    thread-safe per-account transport registry and leases
    rest_connection.py    HTTPX/session/account/refresh implementation
    websocket_connection.py  independent persistent socket
    settings.py           validated .env/environment configuration
    rate_limiter.py       shared request pacing
    errors.py             typed errors
  endpoints/              one module/class per endpoint, inheriting BaseEndpoint
  models/                 one file per response entity and request shape
  analysis/               pandas normalization and NumPy operation statistics
tests/                    mirrors every library module
```

Endpoint classes inherit `BaseEndpoint -> BaseService` and access the same `RestConnection`. Connections inherit `BaseConnection`. Data models use the separate `Record`/`Request` hierarchy; they intentionally do not depend on live network sessions. The facade owns resource lifetime. Two facades with identical settings share the singleton and each hold one lease; closing one does not break the other. Closing the final owner releases the pool/socket. A new owner can then create a fresh session. Direct construction of connection classes is rejected; use the facade (or low-level `acquire()` with a matching `release()` if embedding).

The singleton registry is process-wide, with a separate REST/WebSocket instance for each broker origin, broker ID, login email and account ID. Multiple accounts can operate simultaneously in one process or container. Identical account settings reuse their connection; conflicting settings for an already-open account are rejected until its owners close. Requests are serialized within each account session to avoid concurrent authentication-state changes. Accounts on the same platform origin share a conservative aggregate request budget, using the lowest configured rate among its active limiters. No instance or credential is created at import time. Context managers and explicit `close()` are supported; callers must use one of them.

## Analysis scope

`api.dataframe()` exposes complete preserved response data as pandas columns. Nested child positions remain nested instead of being added to their parents and double-counted. `api.analyze_closed_operations()` provides count, wins, losses, breakevens, net P&L, win rate, profit factor, and realized-P&L drawdown using pandas and NumPy. These are **closing-operation** statistics: partial-close rows are not silently merged into completed round trips. `None` profit factor means no losing operations; drawdown is in P&L currency units and excludes floating equity. Analyze a single account/currency at a time. It uses the API's `netProfit` field without assuming the Manager UI's differently described label has the same meaning.

This is the initial analysis foundation, not a claim that all possible financial analyses are already implemented. You can use the returned DataFrames with the full pandas/NumPy toolsets.

## Tests and validation

```powershell
poetry install --with test
poetry run python -m pytest
poetry run ruff check src tests scripts
```

There is a dedicated test file for every library module, enforced by `test_module_coverage.py`. Tests use mocked HTTP and socket transports and prohibit real socket connections. They cover the 19 endpoint contracts, all request/response shapes, shared-owner cleanup, settings/secret handling, error behavior, authentication refresh, WebSocket bounds, and numerical analysis. Test coverage and the exact final result are recorded in `docs/VALIDATION.md`.

## Contract boundaries and references

- [Platform API](https://app.theneo.io/match-trade/platform-api/introduction): public REST contract; 500 requests/minute stated. This client defaults to 450/minute with no burst.
- [Current close operation](https://app.theneo.io/match-trade/platform-api/position/close-positions): `/position/close`, not the older PDF's plural path.
- [Pending create](https://app.theneo.io/match-trade/platform-api/order/create-pending-order): current example uses LIMIT. STOP is listed in the older official specification; native STOP_LIMIT is not verified. The client rejects STOP_LIMIT rather than silently translating it.
- [Market Watch](https://app.theneo.io/match-trade/platform-api/data/market-watch) and [Login](https://app.theneo.io/match-trade/platform-api/login): cookie descriptions conflict; deployment verification is required.
- [HTTPX connection pooling](https://www.python-httpx.org/advanced/clients/) and [websockets synchronous client](https://websockets.readthedocs.io/en/stable/reference/sync/client.html).

Manager Application administration and its Token/HMac credentials are a separate interface; this SDK does not invent Manager API routes from GUI features. There is no verified broker-specific websocket implementation, idempotency guarantee, history pagination, server-side label correlation, trailing-stop setter or MFA workflow in this initial version. Unknown API collection wrappers fail visibly; instrument list/single-object and quotation list/body-wrapper variants are supported. No live-trading compatibility claim is made until you run the read-only checks against your actual broker.
