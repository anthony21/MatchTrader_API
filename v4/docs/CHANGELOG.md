# Changelog

Application releases use `major.minor.patch`; development stays in `v4/`.
Breaking contracts increment major, compatible features increment minor, and
compatible fixes increment patch. Each new release receives an annotated Git tag
matching the Python and frontend package version.

## 1.0.0 - verified-trade ledger, copy controls and push-only shell

Record, for every copied trade, the broker's own read-back as the only proof of
arrival. A trade is verified only when an open-positions or closed-history read
returned its exact position id with matching symbol and side and carried
AquaFunded's own open time; a write response can never verify it. Verified open
and verified closed are the only verified states. Local-clock and broker-clock
timestamps stay in separate labelled columns. Every failed or unconfirmed write
records an investigable reason with origin broker, local, transport or unconfirmed;
nothing is recorded as a bare unknown. See VERIFIED_TRADES.md.

Copy controls add a Paper/Live master switch and per-source switches for P01, X17
and MANUAL, persisted in data/dashboard/copy-controls.json and defaulting to paper
with every source off. An enabled source is eligible and visible; nothing is sent
automatically. Sending is an explicit action on a candidate row with lot size as the
only editable field, sent at most once in either mode. Paper records the exact
request and never contacts the broker; Live also requires MTR_ENABLE_WRITES=true
and the connected destination account. TradingBox PAMM publication happens only
after verification, is recorded per attempt, is never retried automatically and
never confirms or invalidates a trade.

New Verified trades and Paper trades pages. The shell no longer polls its own API:
status, feeds, mappings, broker profiles, copy controls, verified trades and paper
sends arrive on one authenticated stream and only changed sections are resent.
Broker orders and positions, which live upstream, refresh every five seconds only
while connected with orders or positions outstanding. X17/P01 ingestion from the
x.0.1 workspace, the local relay and the Start/Stop launcher are included in this
release; the P01 diagnostic log is observed only.

The major version is incremented because the mapping journal schema moves from
1.0.0 to 1.1.0 and the change is not backward compatible. A 1.0.0 journal is
migrated in place on first open, forward-only; older code cannot open a migrated
journal and there is no downgrade path. Back up
data/dashboard/quantower/capture.sqlite3 (with any -wal and -shm files) before the
first run. Event schema stays 1.1.0. Known limits: a trade resolved by a close
write response is not revisited for closed-history read-back and stays verified
open; two identical closes without broker execution ids collapse to one row, which
can only under-count closure; live end-to-end copying to AquaFunded is not
established by the test suite.

## 0.9.1 - platform-first login and session status

Show only PLATFORM_NAME in the first dropdown, with login beside it and that
platform's account choices below. Switching platform changes the displayed
connection status and account data. Reuse unexpired logins held on the backend;
expired sessions require refresh and unknown expiry is labeled explicitly.

## 0.9.0 - choose a broker login and returned account

Choose a named .env login, retrieve its available trading accounts, and open a
session for the selected account. Friendly PLATFORM_NAME values accept mixed-case
environment names. Empty account IDs no longer prevent dashboard startup. Account
switching clears the previous snapshot and keeps other profiles separate; MTR
switching requires capture stopped. Credentials and broker tokens stay on the backend.

## 0.8.2 — complete the TradingBox HTTP return path

Forwarding now covers HTTP requests under /api/hcamm/, including command polls and acknowledgements. Preserve methods, original query strings, body bytes and upstream replies; correlate logs by method, path and request cycle. Support bounded chunked requests. Both Copy settings controls still gate all upstream traffic and reset off on restart.

## 0.8.1 — TradingBox forwarding controls

Copy settings now controls Off, Preview and Live delivery for incoming TradingBox signal requests. Bodies and end-to-end headers pass through unchanged; correlated request/response logs distinguish local recording, upstream replies and unknown delivery outcomes. No automatic retries, redirects or history replay. Forwarding and Live always start off; Aqua copying stays separate.

## 0.8.0 — concurrent broker profiles

Load up to five explicit .env profiles such as MTR and GTR. Connect, refresh and disconnect each separately; balances, currency, orders, positions and errors remain scoped to the broker/account. The primary workspace reuses its existing connection. No multi-destination copy routing is introduced.

## 0.7.1 — logging-only observation patch

Opaque authenticated event receipts, bounded private archive and saved-log viewer. Unknown JSON/text/binary events are observations only; no forwarding or copying is added.

## 0.7.0 — live raw event viewer

- Inspect incoming WebSocket application messages before validation and receiver
  replies, including rejected event diagnostics, with local receipt timestamps.
- Search JSON, filter direction, expand messages and pause the display without
  stopping capture. Authenticated native HTTP traffic is labeled separately.
- Keep diagnostics in a rolling memory buffer: 500 entries / 2 MiB serialized
  maximum; no additional diagnostic files or SQLite rows. The trade journal and
  the separate sender's receipts are unchanged and still require storage planning.
- Validate with raw-buffer bounds/redaction tests, rejected-message WebSocket
  integration, frontend tests and browser checks. No live trade was submitted.

## 0.6.0 — readable Orders and accumulated capture improvements

This is the first tagged release after the initial repository import. The changes
below were developed as local milestones and are published together in focused
commits. Versions 0.2.0–0.5.0 describe those milestones, not separate Git releases.
Intermediate commits organize review; the release tag identifies the complete,
validated application.

### Orders workspace (0.6.0)

- Replace UUID headings with instrument, direction and source labels. Internal
  trade IDs remain available under expandable, copyable details.
- Separate open positions, pending orders and copy activity. Show readable sizes,
  entry prices, stop loss, take profit and available broker profit/loss.
- Add search, review filters, pagination and responsive cards. Captured source
  events remain distinct from confirmed broker activity.

### Quantower receiver (0.5.0 milestone)

- Receive native events over an authenticated local WebSocket with bounded queues,
  durable acknowledgements, duplicate protection and sender health.
- Measure dispatch stages and move CSV export off the dispatch path. These
  measurements do not establish a guaranteed 10 ms broker transfer time.
- Document the separate C# sender contract and include an interoperability client.

### Live incoming feed (0.4.0 milestone)

- Push native journal updates to the browser using an authenticated event stream,
  with reconnect recovery and polling fallback.
- Preserve separate account status and broker snapshot refresh cadences.

### Incoming trades (0.3.0 milestone)

- Add React rendering with account and strategy filters and separate lifecycle,
  action, opening evidence and result fields.
- Define backend event meanings so observation, acceptance and fills remain distinct.

### Trade identity (0.2.0 milestone)

- Persist source and broker order/position relationships, partial executions,
  merged-position evidence and uncertainty holds.
- Publish event schema 1.1.0 and mapping schema 1.0.0 without guessing broker links.

### Setup and compatibility fixes included in this release

- Standardize dependency installation on Poetry and update Docker/source packaging.
- Configure a TLS 1.3 minimum by default while retaining certificate verification
  and the application's explicit HTTP User-Agent.
- Format display timestamps in local time and preserve available order profit.

### Validation and limits

- 287 Python tests, 37 frontend tests and seven browser checks pass; Ruff and the
  production frontend build pass.
- Tests use isolated fixtures. This release does not establish a live end-to-end
  Quantower-to-Aqua copied trade or validate the Docker runtime.
- Trading remains explicitly armed, demo-only and dependent on configured source
  attribution and quantity conversion. Credentials and journals are not published.

## Future patches

Add the newest release above 1.0.0, stating the user-visible problem, resulting
behavior, relevant validation and any remaining limits. Keep commits focused;
several commits may belong to one release. Do not increment a version for every
documentation or test commit. Keep package versions aligned and tag the tested
release commit, without moving existing release tags.
