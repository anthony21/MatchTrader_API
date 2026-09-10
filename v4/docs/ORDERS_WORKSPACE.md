# Orders workspace (0.6.0)

Orders now uses React inside the existing Vue shell, matching the incoming-event
workspace. Summary cards and tabs separate Open positions, Pending orders and
Copy activity. The Orders page removes the large service/session panels above the
trades; account controls stay available and the bridge keeps its service panels.

Instrument, direction, attribution, size, entry, SL/TP and broker-provided P/L lead
broker cards. Net P/L takes precedence, including a genuine zero. Missing values
are unavailable, not invented. Pending orders display Waiting to fill and have no
P/L. Unloaded, empty and disconnected/saved snapshots have separate messaging.
Times remain local; decimal strings retain their supplied precision.

Copy activity leads with the recorded symbol, side and strategy rather than a
UUID. The mapping API adds symbol/side/source fields from its existing trade record;
no IDs or database schema are changed. Observed records say Source captured, not
broker opened. Allocation reasons, partial quantities, fills and action history
remain available in expandable details. Internal Trade ID and native/broker IDs
can be selected or copied there. A reference identifies linked records; it does
not prove an execution. Missing instrument/attribution is explicitly labeled.

Search accepts instruments, strategy and full IDs, including exact account-scoped
source mappings for broker rows. Multiple contributing source trades don't become
one guessed strategy. Needs review filters mapping uncertainty/reasons. Pagination
shows 12 records per page; the underlying mapping feed remains its existing bounded
latest-200 window. No currency/P&L totals are calculated across inconsistent inputs.

The refresh button uses the existing read-only order/position snapshot endpoints.
Five-second broker refresh, WebSocket capture and trade routing are unchanged.
Existing standalone Vue table components are retained for compatibility; the Orders
route now mounts OrdersWorkspace.vue and Orders.jsx.

Validation covers React/Vue integration, readable headings with collapsed IDs,
exact precision and zero P/L, linked strategy search, ambiguity, copy interaction,
filters/pagination, snapshot states, and desktop/mobile browser rendering. The
mapping API metadata is tested against recorded source events.
