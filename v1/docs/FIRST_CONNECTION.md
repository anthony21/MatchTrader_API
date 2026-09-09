# Registration and initial connection

The [Platform API documentation](https://app.theneo.io/match-trade/platform-api/order/get-active-orders)
defines two onboarding paths:

| Situation | Documented request sequence |
| --- | --- |
| Existing trading-platform user | Obtain `partnerId` from `GET /manager/platform-details` (or broker configuration), then `POST /manager/mtr-login` with email, password, and that ID as `brokerId`. |
| New user the broker intends to create | `POST /manager/user` with broker-provided `offerId`, `partnerId`, email and password; use the returned one-time token with `POST /manager/login/co/with-token`. |

`Register` creates a platform user. It is not a documented registration of a
Python application or approval of an existing browser challenge. Existing accounts
use the login flow. A broker must provide the appropriate offer before new-user
registration; the dashboard does not create additional users automatically.

Login returns accounts and authentication material. Select the intended trading
account, use its trading API token and system UUID, and maintain the authenticated
session cookie. The SDK keeps these values on the backend and refreshes the session.

## Local application setup

1. Preserve the existing `.env`. Fill `MTR_PLATFORM_URL`, `MTR_EMAIL`,
   `MTR_PASSWORD`, and `MTR_ACCOUNT_ID` with broker-provided details.
2. Start the dashboard using `docs/DASHBOARD.md`. Click **Connect account**.
   The backend uses the password login flow above and lists returned account IDs.
3. Click **Refresh orders** for an account-specific read. Connection success and
   successful order retrieval are separate checks.

With `MTR_BROKER_ID` configured, login goes directly to `/manager/mtr-login` and
does not depend on platform-details discovery. The actual Aqua response supplied
by the owner uses `accounts` and `selectedAccount`; the SDK supports those and the
documentation's `tradingAccounts` and `selectedTradingAccount` names. Account tokens
are kept separate and excluded from model serialization.

Standalone SDK login on the Windows VM was verified on September 9, 2026, after
comparing a successful Postman request on that same VM. HTTPX's default
`User-Agent: python-httpx/0.28.1` received HTTP 403 with a Cloudflare challenge.
Changing only the User-Agent in an otherwise matched balance read to the SDK's
own `hcamm-matchtrader/0.1.0` identity returned HTTP 200. The SDK now sends that
identity on all requests, including login and refresh. No Postman cookie import
or browser interaction is needed for the verified password-login workflow.

The successful SDK uses the canonical single-slash paths, JSON headers and
HTTP/1.1. Postman's double-slash login path and HTTP/2 were also compared; neither
change alone fixed HTTPX. The internal broker filtering rule is not known, and
this observation is specific to the tested client and broker configuration.

The existing SDK also exposes `register()` and `login_with_token()` for a separately
authorized new-user flow. They have offline endpoint tests. An existing funded
account should not be recreated as a connection troubleshooting step.

## Confirmed Aqua balance mapping

This mapping returned HTTP 200 from both Postman and the standalone SDK:

| Request value | Source |
| --- | --- |
| Base origin | `https://platform.aquafunded.com` |
| Account | Match `accounts[].tradingAccountId` to the explicitly chosen account; use `selectedAccount` only when it is that account. |
| System path | Chosen account's `offer.system.uuid` |
| Trading header | `Auth-trading-api: <chosen account's tradingApiToken>` |
| Session cookie | `Cookie: co-auth=<top-level token>` |
| Balance path | `/mtr-api/<system UUID>/balance` |

Send `Accept: application/json` and `Content-Type: application/json`; the GET has
no body. For Aqua, leave `MTR_TRADING_URL` and `MTR_SYSTEM_UUID` blank so the client
uses the platform origin and derives the system per account from login. Do not use
the internal HTTP `tradingApiDomain` in the response as a public API origin.
The SDK regression test covers differing account tokens/system IDs, the top-level
cookie, and an internal domain that must not be used. Live SDK verification on
the VM covered login, balance, active orders, open positions, refresh, and a
subsequent balance read. Empty order/position lists were returned; parsing of
populated lists and order submission remain separate validation work.

## Session renewal workflow

Primary reference: [Refresh token](https://app.theneo.io/match-trade/platform-api/refresh-token).
The documented renewal operation is `POST /manager/refresh-token`, using the
refresh cookie from login. The SDK preserves the HTTP cookie jar and processes
`Set-Cookie` updates. A copied login JSON body alone does not contain that cookie jar.

Use `MTR_SESSION_RENEWAL=refresh` (the default and the Aqua configuration). On the
next trading request after 15 minutes, the client refreshes before sending it. A
read-only 401 also permits one renewal and one retry. Renewal attempts are capped
at four per hour per account connection; a failed renewal surfaces an error. There
is no background keepalive while idle and no automatic replay of trading mutations.

```python
from matchtrader import MatchTraderAPI, Settings

with MatchTraderAPI(Settings.from_env()) as api:
    auth = api.login()          # credentials stay in .env / backend memory
    orders = api.active_orders()
    api.refresh_token()        # optional explicit documented refresh
    # Later reads automatically refresh when due.
```

The live Aqua refresh returned HTTP 200 with an empty body, followed by a successful
balance read. Refresh supports an empty response with cookie updates, a JSON session token, or
an account-bearing JSON response. If account tokens are returned, the selected
account's tokens are replaced together. Support for these shapes is unit-tested;
it does not assert that Aqua returns every variant.

For a separately established broker workflow that renews through password login,
`MTR_SESSION_RENEWAL=login` is an explicit alternative. It obtains a fresh login
response on the same demand-driven schedule and preserves the selected account.
This alternative is not the documented refresh operation and is not enabled for
Aqua. Explicit `api.login()` remains available for a fresh session. The Python
login method accepts `username`/`brokerid` aliases but sends the documented JSON
field names `email`, `password`, and `brokerId`.
