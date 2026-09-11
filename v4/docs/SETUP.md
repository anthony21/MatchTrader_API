# Install and run v4 0.8.2

For the current 0.9.0 workspace, **Choose broker login** opens the named .env
profile selector. **Log in and list accounts** retrieves the broker's account
choices; **Use selected account** opens the selected session. Account IDs can
be left blank at startup. Mixed-case PLATFORM_NAME labels are supported. See
[the updated account flow](BROKER_PROFILES.md). The tagged install commands
below still reproduce the published 0.8.2 release.

## Fresh installation on Windows

Install Python 3.12 or later, Poetry 2.2 or later (2.x), Git, and Node.js 22.12
or later with npm. Use the locked dependencies. Do not copy another machine's
.venv or node_modules directories.

```powershell
git clone https://github.com/anthony21/MatchTrader_API.git
Set-Location .\MatchTrader_API
git checkout v0.8.2
Set-Location .\v4
poetry install --with test
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
notepad.exe .env
```

All remaining commands run from v4 using its own .venv. For a source handoff ZIP,
extract it and enter the folder containing pyproject.toml instead of cloning.
Preserve existing credentials and journals when upgrading. Process environment
variables override .env. Never put secrets in frontend source or Git.

## Environment configuration

Supply the main broker's MTR_PLATFORM_URL, MTR_EMAIL, MTR_PASSWORD, MTR_BROKER_ID
and MTR_ACCOUNT_ID. Use the broker's Match-Trader terminal URL. Omitting the broker
ID triggers platform-details discovery before login. Use the original working
cookie mode; session is the example default. Leave MTR_TRADING_URL and
MTR_SYSTEM_UUID blank unless explicit values are required by the broker.

The SDK retains its hcamm-matchtrader/0.1.0 User-Agent and normal certificate
verification. The dashboard can start without connecting to a broker. Forwarding
alone does not require broker credentials: retain a syntactically valid
MTR_PLATFORM_URL and leave the broker disconnected.

For native Quantower capture, generate a separate local sender secret:

```powershell
poetry run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save it as MTR_BRIDGE_TOKEN and in the native extension's configuration. This is
separate from broker credentials and the TradingBox signal key. The native socket
defaults to port 8767 and remains disabled without a bridge token. Set
MTR_CAPTURE_WS_PORT=0 to disable it explicitly. See the
[native sender handoff](QUANTOWER_SENDER_HANDOFF.md).

## Start, stop and upgrade

```powershell
poetry run python -m matchtrader.dashboard.cli
```

Or use the installed environment directly:

```powershell
.\.venv\Scripts\python.exe -m matchtrader.dashboard.cli
```

Open **http://127.0.0.1:8765**. Keep the terminal open; stop with Ctrl+C. Restart
after changing .env. After updating source, reinstall the project, rebuild the
frontend and restart. If port 8765 is occupied, stop the previous instance first.
Do not run two instances against the same journal. TradingBox relay routes work
with native capture stopped and the broker disconnected.

## X17 to TradingBox forwarding

The exchange is **X17 -> localhost relay -> TradingBox -> reply to X17**. It does
not require the native WebSocket extension to translate X17 payloads. Only traffic
addressed to this relay can be observed or controlled.

1. Set TB_FORWARD_API_KEY to the exact signal key/header value used by X17's
   working TradingBox connection. The PAMM read-only key is a different credential.
2. Set TB_FORWARD_AUTH_HEADER to X-HCAMM-Key (default), X-API-Key, or Authorization,
   matching X17. For Authorization, include the original Bearer prefix in the
   configured value when applicable. Restart the application.
3. Open **Copy settings -> TradingBox signal forwarding** and save the original
   upstream URL: https://tradingbox.pro/api/hcamm/events or
   https://tradingbox.org/api/hcamm/events. The selected host is used for every
   relayed /api/hcamm/ path.
4. Set X17's event destination to **http://127.0.0.1:8765/api/hcamm/events** and
   retain its original authentication and event IDs. Change any separately
   configured command polling or acknowledgement URLs to the same local origin,
   preserving their paths and query strings. For example, /api/hcamm/commands
   keeps the indicator's original machine and cursor parameters.
5. **Turn forwarding on** enters Preview. Requests are logged and receive an
   explicit local HTTP 202 receipt. No upstream calls occur. This receipt is not
   a TradingBox acceptance or broker fill.
6. **Go live with TradingBox** forwards newly received requests and returns actual
   upstream replies. Delivery can trigger TradingBox's configured trades. Do not
   also send duplicate copies directly to TradingBox.
7. **Turn forwarding off** blocks new sends and clears Live. Already admitted
   requests may finish. Both controls reset off on restart; only the destination
   URL persists. Archived events are not replayed. These controls do not cancel
   or close existing trades.

Methods, query strings, authentication, payload bytes, status and end-to-end reply
headers pass through. Host, connection framing and TLS belong to each leg. The
relay supports GET, HEAD, POST, PUT, PATCH, DELETE and OPTIONS under /api/hcamm/.
It is not a WebSocket tunnel or proxy for other namespaces. Request/reply bodies
are bounded to 1 MiB and request trailers are unsupported. The relay does not
automatically retry or follow redirects. See the
[full forwarding contract](TRADINGBOX_FORWARDING.md).

## Logs and separate broker accounts

- **Raw events** displays redacted, volatile request/reply previews with bounded
  memory. It is not an unlimited archive.
- **Event logging** pairs requests and responses by cycle ID and shows method,
  path and upstream status. Query values and authentication headers are not
  archived. Bodies above 64 KiB have explicit archive truncation. Retention is
  2,000 records / 8 MiB of bodies, plus SQLite overhead. Executable trade journals
  have separate retention.
- **Broker accounts** supports up to five complete profiles such as MTR, GTR,
  THIRD, FOURTH and FIFTH. Each supplies its own PLATFORM_URL, EMAIL, PASSWORD,
  BROKER_ID and explicit ACCOUNT_ID. Use Connect configured accounts or individual
  card controls. Credentials, IDs, sessions and snapshots stay separate. See
  [profile examples and limits](BROKER_PROFILES.md).
- Existing **Aqua API copying** is configured separately from TradingBox
  forwarding. Connecting five profiles does not automatically copy to five
  destinations. See [copy configuration](MANUAL_COPYING.md).

A signal receipt, upstream acknowledgement, broker order acceptance and fill are
different stages. Use actual upstream replies and broker records to establish
what happened; a chart marker alone does not prove an event was sent.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No X17 events | Confirm X17 publishes to localhost. Native extension observations do not automatically expose internal X17 intents. |
| Sender gets 401 | Match the exact TB_FORWARD_AUTH_HEADER and key in the sender and .env; restart. Browser-origin calls to native relay routes are rejected. |
| HTTP 202 | Forwarding is off, Preview is active, or controls changed before request admission. |
| Upstream 403 | Confirm the original host and authentication. Mock tests do not prove live acceptance. |
| HTTP 502 uncertain | Check TradingBox before manually resending a potentially executed signal. |
| Broker profile cannot connect | Supply its explicit ACCOUNT_ID and complete credentials; values are not inherited from MTR. |
| Old behavior | Reinstall, rebuild frontend assets, restart, and check the import path below. |

```powershell
.\.venv\Scripts\python.exe -c "import matchtrader; from matchtrader.version import VERSION; print(matchtrader.__file__); print(VERSION)"
```

The import should point inside this checkout and show version 0.8.2.

## Tests and source handoff

```powershell
poetry run python -m pytest --basetemp data/pytest-release -o cache_dir=data/pytest-cache --no-cov
poetry run ruff check src tests scripts
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
poetry run python scripts/build_handoff.py --output dist/matchtrader-0.8.2-handoff.zip
```

Release verification: 330 tests in the full backend run, then 20 focused transport
checks including two added method cases; 41 frontend tests; three relevant browser
checks; production build, Ruff and Poetry checks. Upstream forwarding tests use
simulated calls. Live X17/TradingBox compatibility and Docker remain separate
validation work.

The handoff contains a SHA-256 manifest and excludes .env, runtime data, local
dependencies and the separate x.0.1 workspace. Earlier v1-v3 source remains in Git
for history, but is not part of the v4 handoff.
