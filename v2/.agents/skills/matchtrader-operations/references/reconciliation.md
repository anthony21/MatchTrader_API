# R01 / relay / broker reconciliation

Pin an explicit UTC interval `[start, end)` and the account. When asked to analyze an
existing Last 24h export, use the export's recorded time as the snapshot boundary
instead of silently replacing it with a later rolling window. For broker timestamps
without offsets, establish timezone from a broker response/configuration or retain
them as source-local. Any inferred alignment must be labeled and cannot support a
claim of measured network latency. Include pre-window intents for orders that filled
or closed within the window.

## Inputs and their meaning

- `R01_TRADES.csv`: UTC events; `intent`, `regrade`, `cancelled`, and `touched` are
  strategy observations. Newer rows can have extra trailing CSV fields; preserve them
  rather than shifting the documented leading columns or skipping the row.
- Quantower `HCAMM R01*/logs/*.slog`: JSON lines, typically `@t` and `ev`. Select by
  event timestamps across instances, not only the newest folder or filename date.
- Relay/verdict logs: retain destination, label, clientEventId, sequence, verdict,
  and broker IDs when present. Deduplicate genuine replay IDs, not merely equal text.
  A local refusal can coexist with a relay send; the two execution paths are separate.
- Broker closed-history export: order/position IDs, fill/open time, actual entry,
  stored SL/TP, close time/price, volume, displayed profit and reason. A fill timestamp
  does not reveal when the broker received the pending order. Final SL/TP can differ
  from original requested SL/TP after edits.

## Match conservatively

Prefer an explicit correlation chain: R01 event ID -> relay acknowledgement -> broker
order ID -> position/close ID. Scope all identities to account and strategy instance.
Labels and box IDs can be reused; include intent time and lifecycle to distinguish them.

If IDs are absent, use symbol, side, price precision, SL/TP, time ordering, and available
lifecycle evidence. Price-only or nearest-time matches are candidates, not confirmed
identity. Preserve alternative matches and state the tolerance. Do not hide mismatched
entry levels, cancellations before broker fills, regrades, partial closes, or multiple
broker orders corresponding to one candidate strategy state. Price-rounding behavior
must be observed or documented; don't assume round-half-even, truncation, or tick size.

Provide columns for source row, candidate label, intent/state time, requested entry,
SL/TP, actual send time if logged, acknowledgement time if logged, broker ID, fill time,
entry/SL/TP, close time/price, profit, outcome, and match confidence. Missing evidence
stays blank with an explanation. Distinguish a new order intent from a later bracket
change. Requested-to-filled price differences can include spread, pending-order fill
behavior, and routing effects; they are not automatically execution slippage.

## Statistics

State the denominator: profitable closed operations / all closed operations, with
breakevens counted in the denominator. Also show wins, losses, breakevens, realized
profit, and account/currency. If partial closes exist, call them closing operations
unless their round trips can be reconstructed. Report the overall broker result
separately from results attributed to confirmed R01 matches. Do not call strategy
backtest wins or quote touches broker wins, or unfilled intents losing trades.

Validate unique IDs or composite close IDs, row coverage, summary-row exclusion,
totals, candidate counts, and source hashes. Use synthetic tests for ambiguous matches,
repeated labels, missing acknowledgements, timezones, footer handling, and rounding.
