# Broker session ownership

The v3-base application owns authentication in `sessions/SessionManager`, above
the unchanged MatchTrader SDK. Its registry maps broker keys to independent token
containers. A broker login supplies the session token, refresh cookies, and all
returned accounts with their trading tokens and system identifiers. Credentials
and tokens stay on the Python side and are never included in dashboard status.

Consumers receive `AccountSession(manager, broker_key, settings)` handles. These
contain an explicit account identity, not an open network connection. Account
switches reuse the broker's login. Each endpoint invocation opens a temporary
SDK view, installs one complete authentication snapshot, invokes the existing
SDK endpoint, and closes the view, including after failure. HTTP traffic now
uses a reusable asynchronous socket pool per broker; token storage remains
separate. Pools open sockets only when requested and expire idle keep-alives. Different
brokers never reuse authentication. Duplicate broker identities are rejected.

## Renewal and lifecycle

Every logged-in broker has its own background worker, independent of browser
polling, capture, and other brokers. The next renewal is scheduled for the JWT's
`exp` timestamp minus 180 seconds. The expiry claim is used for scheduling, not
as cryptographic verification. Missing or unusable expiry fails authentication;
the application does not guess a token lifetime.

Requests use snapshots, so a slow trade/read cannot hold up renewal. Renewal
publishes all replacement tokens together. A token-only refresh retains the
account mapping; an account-bearing response replaces it, so removed accounts
cannot continue trading. Refresh cookies retain their host/path restrictions.
`session_renewal=login` uses configured reauthentication instead of the refresh
endpoint. Neither mode inherits the SDK's four-renewals-per-hour client limit.
If the refresh endpoint rejects authentication, the same session owner attempts
a fresh login with that broker's configured credentials.

Renewal failure pauses broker requests and retries after 2, 4, 8, 16, then 30
seconds, capped at 30. The dashboard displays the failure and next attempt.
An authentication rejection schedules renewal but never replays the failed
request. An unchanged token expiry is not accepted as successful renewal.

Manual disconnect clears that broker's cache and stops its worker. Closing an
account handle does not disconnect the broker. Application shutdown stops all
workers and closes all pools. Disconnect waits for already-dispatched requests
to finish before closing its pool. Queued requests cannot cross a disconnect/reconnect
boundary. Already-dispatched requests can finish after disconnect; disconnect
does not cancel broker orders. Sessions are memory-only: after an application
restart, explicitly connect again. OS suspension, network failure, or upstream
rejection can prevent a scheduled renewal from succeeding; the app reports
this rather than presenting an invalid token as connected.

## Configuration

Existing `MTR_*` configuration remains the default single broker. To name it
and add another MatchTrader broker, add these entries to the private `.env`:

```dotenv
MTR_BROKERS=AQUA,GTR
MTR_PRIMARY_BROKER=AQUA
AQUA_LABEL=AquaFunded
GTR_LABEL=GooeyTrade
# Existing MTR_* settings belong to the primary broker, AQUA.
GTR_PLATFORM_URL=https://your-other-terminal.example
GTR_EMAIL=your-email
GTR_PASSWORD=your-password
GTR_ACCOUNT_ID=your-default-account
GTR_SESSION_RENEWAL=refresh
```

Each nonprimary broker uses its own `KEY_*` Settings fields. An account ID is
optional: connect the broker to discover its accounts. The default account is
chosen from that broker only; an explicitly configured missing account is never
silently replaced. Broker keys must be unique uppercase identifiers. Configure
one profile per broker; accounts under that broker belong in the same login.
Profiles are loaded at startup. No broker credentials are edited in the browser.

The registry's adapter protocol can accommodate other broker APIs and future
data feeds. Only MatchTrader is implemented now; adding a name such as APEX or
TOP does not implement that provider's API.

Async socket pooling, timeout configuration, and the awaitable account API are
documented in [ASYNC_TRANSPORT.md](ASYNC_TRANSPORT.md).

## Dashboard and SDK boundary

The dashboard shows each broker's state, accounts, expiry, and next renewal.
Open **Broker sessions** in the sidebar to manage connections and account selection.
Each broker has its own card; connected brokers are green. Accounts returned by
login populate its dropdown. Connect is disabled while connected; Disconnect is
disabled while disconnected. Selecting a different connected account reuses the
broker session. Start/Stop capture controls remain only on **Trading bridge**.
Changing pages, selecting another broker, losing browser focus, or reloading the
page preserves backend sessions and their renewal workers. Returning to browser
focus reads current status; it does not log in again. Browser timers are only
for display and snapshots, never token renewal.

Stop capture leaves the selected broker authenticated and available to consumers.
Use the separate Disconnect button to end that broker's session. Other broker
sessions continue. Selecting another broker during capture does not retarget
incoming events: ingress remains attached to the broker where capture started.
Only one broker can own the shared capture ingress at a time. The dashboard
shows its owner and blocks starting a second capture until the first is stopped.

The primary broker retains the existing journal location for compatibility.
Additional brokers use `data/dashboard/brokers/KEY/`. Keep the primary broker
identity stable for an existing data directory. The legacy optional capture
route belongs exclusively to that primary broker. Copying starts disabled and
still requires the existing source/account/demo guards. The adapter rechecks
the current destination's demo flag before every routed mutation.

`api.py`, `core/`, `endpoints/`, and `models/` are unchanged. The adapter is the
only application module touching SDK internals: it supplies a transient
`ManagedConnection` and initializes the facade's existing ownership fields.
This deliberately bypasses SDK-owned automatic login/refresh and leased-client
reuse. Future SDK upgrades must rerun adapter contract tests. Standalone SDK and
CLI use retain their original behavior; application consumers use the manager.

Offline tests cover independent brokers/accounts, scheduled repeated renewal,
slow requests, background renewal without a browser, retry backoff, manual
disconnect/reconnect, account routing, transport cleanup, no mutation replay,
and the original pending-order baseline. These tests do not prove live renewal
behavior at a broker. No trade is submitted as part of this implementation.
