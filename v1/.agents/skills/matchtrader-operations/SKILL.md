---
name: matchtrader-operations
description: Connect the Match-Trader Python SDK to broker accounts, retrieve trade history, diagnose browser versus REST access, and reconcile Quantower R01 events with broker executions using explicit evidence.
---

Use the SDK's `agent.md` and `README.md` from the repository root (three directories
above this skill folder). Preserve the user's broker, accounts, language, and scope.

## Connect and retrieve

Use the official Platform API documentation at
https://app.theneo.io/match-trade/platform-api/ as the primary connection reference,
especially https://app.theneo.io/match-trade/platform-api/refresh-token for renewal.
Read `docs/FIRST_CONNECTION.md` for the SDK workflow. When broker ID is configured,
login can proceed directly; platform discovery is not a mandatory extra request.
Keep `MTR_SESSION_RENEWAL=refresh` for the documented cookie-based renewal flow.
Distinguish host-machine/Postman success from requests made inside a Windows VM.

Load credentials locally through `Settings.from_env(path)`. Report missing field
names or validation categories, never secret values. REST settings require HTTPS
origins. A terminal page path such as `/app/trade` is not the API base path.
Confirm the user supplied the intended broker host before sending credentials.

Use a context manager and keep writes disabled for read-only work. Retrieve platform
details, log in, select an explicit trading account, then read balance and history.
Login may return several accounts; don't silently adopt one for mutations. For an
authorized read of any account, choose and clearly identify the account being read.
Use `for_account()` for other accounts, with independently closed handles.

For a Cloudflare/HTML response or an already-open browser, read
[browser access](references/browser-access.md). A challenged request does not prove
the broker has no API or that allowlisting is required. Compare the actual terminal
route, documented route, HTTP status, content type, and challenge header.

## Reconcile and calculate results

Read [reconciliation](references/reconciliation.md) when comparing strategy sends
to broker activity. Inventory the available evidence before choosing joins. Output
the full side-by-side CSV/table, unmatched rows and alternatives, methodology, and
win-rate denominator. A summary alone does not fulfill a request for all trades.

Use `scripts/reconcile_r01.py` from the repository root for the supported R01 CSV
and Match-Trader closed-export schemas; see the README command. This helper performs
level-based candidate matching, not a shared-ID join. Confirm account/window metadata
from the export UI. Its default price tolerances are for the observed XAUUSD workflow;
review or adapt them for another instrument. Do not describe its blank send/receipt
fields as measured values or claim its candidate classification proves routing.

## Package

Build with `scripts/build_handoff.py`; do not archive the entire working directory.
Validate the archive's manifest, run appropriate tests, and include known gaps in
the handoff. The SDK's desktop session and private data are not portable components.
