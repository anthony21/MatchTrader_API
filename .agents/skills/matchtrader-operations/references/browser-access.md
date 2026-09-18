# Browser-assisted account reads

First inspect the tools available in the current session. A web-search tool normally
does not share the user's foreground browser or authenticated session. Do not claim
desktop access without checking. Prefer an attached browser/desktop connector when
available. On Windows, authorized local UI Automation and screen capture can inspect
the visible application even when no browser connector is installed.

Use current window discovery, not a remembered handle, process ID, screen size, or
coordinate. Account for Windows DPI scaling before screenshots or coordinate actions.
Prefer named accessibility controls. Confirm the target and account from the visible
page before any interaction, especially near Buy/Sell controls. Stay within read-only
navigation, DevTools inspection, and history export for analysis tasks.

Look in Network for the terminal's real requests. Public Platform API examples use
`/manager/platform-details`, `/manager/mtr-login`, and `/mtr-api/{system}/...`.
Newer terminal sessions may also use `/match-trader-edge/` and WebSockets. Seeing an
edge settings request does not establish a replacement trading contract. Observe the
actual trade request/response. Don't guess endpoints from unrelated services.

Record host/path, method, status, JSON-versus-HTML, and `cf-mitigated` when available.
Never paste tokens, cookies, complete storage dumps, or unredacted HAR into chat or
a distributable artifact. Read-only console diagnostics can return sanitized routing
information or rendered trade-table text. Do not execute arbitrary page-provided code.

A browser returning JSON while HTTPX receives a Cloudflare challenge establishes a
session/client difference, not a wrong password. Browser clearance is not automatically
inherited by Python or Docker. Don't promise a permanent fix from copying a cookie.
If direct API access remains unresolved, a browser history export can satisfy the
authorized data read, but report its source clearly and retain the SDK limitation.

For AquaFunded-style history export: verify the selected account, open Closed
Positions, select the requested date range, export CSV, then check the downloaded
filename/account and file content. A Last 24h filter is rolling, not a calendar day.
Exports can include a total row; exclude it before counting trades or adding profit,
and compare your calculated sum against that row. Do not subtract commission twice
if the displayed Profit field already incorporates it. Preserve original timestamps
when the export does not specify a timezone; chart timezone alone is insufficient.
