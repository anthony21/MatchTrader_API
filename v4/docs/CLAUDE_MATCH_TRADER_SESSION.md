# MatchTrader session handoff

This branch starts from main at `e693a08` and records the session's work. It is a
documentation handoff, not a release of the implementation described below.
The implementation resides in the separately maintained local `x.0.1/` directory,
which remains excluded from GitHub at the user's prior request. No credentials,
private event logs, runtime journals, or release archives are included here.

## Completed local work

- Shared broker login/session handling for closed-trade history, including named
  platform selection and account-specific views.
- Fixed rejection of valid Quantower HTTP batches above 16 KiB. Local signal
  ingress now accepts up to 1 MiB while retaining the 100-event batch limit.
- Diagnosed the native WebSocket connection separately from X17 HTTP traffic.
  The capture extension and dashboard capture must both be running for native
  order events. X17's structured HTTP messages use a separate receiver path.
- Added a bounded P01 diagnostic-log view with labels, direction, entry, stop,
  target, and distinct intent/removal observations. Missing account, instrument,
  or broker execution evidence is not invented from a chart click.
- Audited X17 raw messages and distinguished strategy intents, lifecycle outcomes,
  repeated deliveries, and structured manual P01 signals. X17 intents supplied
  prices and direction but no executable size or order type.
- Added opt-in P01 log/state correlation for open intents. Only matching label,
  time, side, and price fields can produce a candidate copy. The shared latest-state
  file can miss rapid clicks; mismatches are held.

## Latest local feature: x.0.1 build 0.8.0

Copy settings includes **Use X17 + manual P01 at logged entry**. The user supplies
the destination account, exact symbol mappings, and lots. Saving does not enable
Live. Copies use the destination account's existing authenticated SDK session.

X17 copies retain entry, SL, and TP, and use configured lots without modifying the
publisher's payload. When order type is absent, a fresh destination quote chooses
BUY LIMIT below ask / BUY STOP above ask or SELL LIMIT above bid / SELL STOP below
bid. Equality or an unavailable/stale quote is held; there is no market fallback.
Structured P01 limit/stop values are normalized for parsing, preserving the raw
payload. The combined preset uses structured P01 messages instead of the P01 log
route to avoid duplicate delivery paths for the same manual trade.

The optional chart filter applies to X17's chart interval; a blank filter accepts
all intervals. Order links are scoped by machine, source, source account when
provided, interval, symbol, label, and destination. P01 panel events have no chart
interval. Missing source-account metadata remains missing.

Explicit `cancel`/`cancelled` messages can cancel only the uniquely linked pending
copy. The broker must still report that order with the saved ID, instrument,
side, and type. Filled or absent orders are held; cancellation does not close
positions. X17 `closed` outcome records are observations, not broker fill or
realized-profit evidence, and do not automatically close positions.

Live-off, stale-event, duplicate-event, duplicate-lifecycle, and uncertain-write
protections remain active. Ended intents in the same batch do not open orders.
Uncertain creation/cancellation attempts are not automatically retried, including
after restart. A reused label in the same scope is conservatively held after a
prior attempt. Copy requests, responses, and broker IDs appear in the local UI.

## Validation and remaining limits

The final local feature was checked with 71 distinct backend/HTTP-loopback tests
and 17 frontend tests across the session's validation runs. Ruff, Poetry metadata,
and the frontend production build passed. Coverage included all four pending-type
cases, immutable source payloads, configured lots, lowercase P01 types, interval
and account isolation, pending cancellations, filled-order holds, duplicates,
stale quotes, and uncertain cancellation recovery across restart.

These are recorded results from the local x.0.1 implementation, not claims that
this documentation branch contains or has rerun those tests. Broker writes in
that validation used fakes. No real broker trades or cancellations were submitted
for the final feature, and Live was not enabled. Actual broker quote timestamp
availability and pending/cancel response compatibility remain to be verified.
Prices are not automatically rounded or converted to a different contract scale.

## Repository state at handoff

The pre-existing `feat/verified-trade-ledger` branch was left intact at `1e7e84e`.
It contains these separate v4 commits beyond main:

- `e282aaf`: checkpoint in-progress v4 0.9.1 work.
- `58d0096`: synthesized STOP_LIMIT support.
- `1e7e84e`: broker read-back evidence for verified trades.

Those commits are not merged into this branch and are not attributed to the
X17/P01 work summarized here. Porting the excluded implementation into a tracked
release is separate work; this handoff must not be mistaken for that port.
