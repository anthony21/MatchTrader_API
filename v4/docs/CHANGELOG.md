# Changelog

Application releases use `major.minor.patch`; development stays in `v4/`.
Breaking contracts increment major, compatible features increment minor, and
compatible fixes increment patch. Each new release receives an annotated Git tag
matching the Python and frontend package version.

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

Add the newest release above 0.6.0, stating the user-visible problem, resulting
behavior, relevant validation and any remaining limits. Keep commits focused;
several commits may belong to one release. Do not increment a version for every
documentation or test commit. Keep package versions aligned and tag the tested
release commit, without moving existing release tags.
