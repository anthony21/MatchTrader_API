# Manual copying and P01 RR (v4)

Open the dashboard at http://127.0.0.1:8765. Connect the demo destination, start
capture, and open **Copy settings** in the workspace sidebar. Select the detected
Quantower account (its displayed account number and internal ID differ), select
P01/manual sources, and configure each exact source symbol, destination symbol,
quantity multiplier and maximum lots. Confirm equivalent instruments/prices and
that no other relay is copying the same trades to this destination. Save settings,
then select **Enable copying** on Trading bridge. Stop copying before editing settings.

Settings are stored locally in `data/dashboard/copy-settings.json`. Saving settings
does not log in again or replace the selected account's connection. The dashboard
uses a write-capable SDK lease, but all copy writes require the router's explicit
arming, source route and broker-confirmed demo checks. The CLI/SDK read-only default
outside this dashboard remains unchanged. Arming is never persisted. Events created
before enabling copying, snapshots, old events, duplicates and unknown sources are held.

**Stop copying disables creates, modifications, cancellations and closes.** Capture
and the account connection remain open. Existing broker orders remain untouched.
Resume does not replay missed actions. Check Orders before resuming if source and
destination could have diverged. Route changes are blocked while copied trades remain
unresolved. The CSV limit is configurable; SQLite retains identity tombstones.

## P01 RR uses submitted values

The installed P01 RR tool's `OnOpenClicked` assigns manual boxes a
`P01RR_HHmmss_sequence` label. Its native adapter puts that label in the Quantower
request comment and sends the calculated `Volume` as native `Quantity`, with absolute
SL/TP values. The capture extension classifies this exact label pattern as **P01**.
Named configured strategies take precedence. Mirrored `M:`/`L:` labels and blank
SendingSource values do not become manual trades.

Choose **Mode 0 / Manual**, the intended chart account, and the desired P01 risk/size,
entry, SL and TP. For this integration, P01 must actually place a native Quantower
order. Its **Arm live orders** setting must permit that; the companion panel can
force signal-only delivery even when armed. A signal sent only to TradingBox is not
a native accepted order and is not forwarded by this integration. The receiver does
not read `P01_STATE.json` or infer trades from preview/range/heartbeat files.

Do not interpret P01's risk percentage or cash amount as lots. The copy uses the
calculated submitted quantity multiplied by the explicit symbol conversion. For
example, a multiplier of 1 copies native quantity 0.10 as 0.10 Aqua lots only when
those units are confirmed equivalent. Broker instrument volume limits are checked.
P01 can also publish to TradingBox: disable duplicate routing to the selected Aqua
destination before enabling this copier. The installer does not alter that relay.

Ordinary order-entry sources decoded from the installed Quantower 1.146.18 assembly
are `OE`, `Multiple OE`, `Modify Position screen`, and `Close Position Screen`.
Configure those exact strings as MANUAL in the extension's private `sources` map.
Other chart titles/sources stay UNKNOWN until verified. Modifications/cancels/closes
of an already linked trade use its original attribution and exact IDs.

## Strategy Manager messages

The extension calls Quantower's Strategy.Log for requests, native accept/reject,
fills and account inventory. Messages show UTC event time, source/account, native
ID, label, request ID, quantity, entry, SL and TP. Separate AQUA messages show receiver
decision, broker ID when available, and hold/uncertainty reason. The board's own Time
column uses Quantower's display timezone. HTTP 202 means receiver acknowledgement;
only a router decision of accepted indicates broker acceptance, not a fill.

Keep the installed strategy name **HCAMM Quantower Capture v3** for in-place upgrade
compatibility: Quantower matches updates by that name. Its startup log explicitly
says **v4 native capture attached**. Stop that capture strategy, replace only its DLL,
select its Update button, and Run it. Other strategies do not need restarting.

## Validation boundaries

v4 was tested offline for P01 label attribution, exact submitted bracket copying,
manual cancellation of linked P01 orders, deduplication, off-period protection,
settings persistence and validation, and Strategy Manager message formatting.
The real dashboard logged in to account 123456 and read pending/open orders. The
installed extension produced an account message on Strategy Manager and delivered
it to the dashboard. No new trade was placed as part of v4 validation; a complete
P01-to-Aqua live copy has not yet been demonstrated.

The earlier authorized Aqua pending-order tests established empty HTTP 204 as
successful cancellation. v4 recognizes that exact endpoint/status combination;
empty HTTP 200 and ambiguous write responses still require reconciliation. Native
STOP_LIMIT remains unsupported for copying. Open-position actions require an exact
broker position link; absence or a symbol/price similarity does not establish one.
