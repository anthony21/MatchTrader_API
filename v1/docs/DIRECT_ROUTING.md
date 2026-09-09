# Direct Quantower to Match-Trader routing

Status: a local shadow bridge and Vue dashboard are implemented. Live routing is
not implemented or activated. No strategy relay settings changed and no orders sent.
See [dashboard setup](DASHBOARD.md) for runnable controls and sender contract.

## Intended route

Quantower R01 outbound order event -> local authenticated bridge -> broker-specific
Match-Trader transport -> selected AquaFunded account.

The SDK supplies REST operations. The new bridge supplies authenticated local ingress,
typed events, request previews, persistent event/revision deduplication, and fresh
CSV observation. The dashboard supplies account selection, connection reads,
start/stop controls and a live feed. A compatible Quantower outbound event adapter,
durable live order lifecycle/mapping and working broker execution transport are
still needed before live routing. Shadow deduplication is not live recovery.

The R01 ledger is analysis evidence, not a complete outbound execution contract.
Its intent and regrade rows contain symbol, side, entry and bracket levels but no
order volume. Quote touches are not broker fills; historical rows must not be replayed
as fresh orders. R01's compiled strategy is installed; editable source has not been
located in the inspected workspace or Quantower scripts folders.

## Event contract to establish with the R01 sender

Each event needs source machine, strategy-instance ID, unique event ID, stable
source-order ID, monotonic revision, emitted UTC timestamp, action, destination
route, symbol, side, order type, explicit lot size and applicable entry/trigger/SL/TP.
Send the complete intended state for modifications. Prices and quantities require
broker instrument precision and min/max/step validation.

An adapter must distinguish:

- A new order from an update to an existing pending order.
- A source label re-key from a request to create an additional order.
- A cancellation from a close-position request after a fill race.
- A quote touch from an execution acknowledgement.

Persist source-order -> destination account -> broker order/position ID mappings.
Reject duplicate/stale revisions, and serialize changes per source order/account.
Record a pending dispatch before sending. A timeout or crash after dispatch means
unknown outcome; reconcile the broker before any resubmission. Without broker
idempotency guarantees, do not promise exactly-once execution.

## Broker operations

The current SDK has market-open, pending-create/edit/cancel, position-edit/close,
balance, active-order and position-history methods. The installed browser connector
also uses `/mtr-api/{system}/pending-order/create|edit|cancel` and `/position/open`.
That code is implementation evidence, not a successful live test of this SDK.

Native STOP_LIMIT support remains unverified. Preserve its trigger/limit semantics
in the source contract and hold unsupported events; do not silently turn them into
LIMIT, STOP, or MARKET orders. Preserve explicitly unset versus unchanged SL/TP.

Standalone Python requests previously received a Cloudflare challenge, while an
authenticated browser returned platform-details JSON. First establish repeatable
login/account reads through a supported transport. Browser-assisted execution would
require its own locally authenticated adapter and account checks; screen capture
and a history CSV export are not an execution connection.

## Activation inputs still needed

- The user has selected the destination account, stored locally in `.env`.
  Broker instrument mapping/quantity rules remain to be verified.
- Whether this replaces the existing route or intentionally runs alongside it.
- The outbound event source and lot-sizing rule, including any sizing currently
  supplied by the relay rather than Quantower.
- Handling of existing pending orders and positions. A new bridge must not claim
  ownership or adopt them merely because their price or label resembles a signal.

Prepare a shadow run first: capture new events and validate generated broker requests
without submitting trades. Compare revisions, account routing and order mapping.
Existing user authorization for the requested routing work remains applicable, but
do not guess missing destinations, quantities, or duplicate-execution intent.

## Audit timestamps

Record QT emission, local bridge receipt, outbound request start, broker response
receipt, returned broker IDs, and observed fill/close timestamps. Name each clock and
timezone. Client response-receipt time is not the broker's internal receipt time.
This supplies a correlation chain for future QT/Aqua comparison instead of matching
by price proximity alone.
