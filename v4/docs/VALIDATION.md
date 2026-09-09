# v4 validation ? September 9, 2026

215 Python tests, 16 Vue tests, 4 browser tests and 16 C# checks passed.
Production frontend build and Ruff checks passed. New P01 attribution, logs,
UI settings, CSV retention controls, cancellation 204 handling and upgrade
identity compatibility are covered. The running v4 dashboard connected to demo
123456 and read pending/open orders. The installed extension logged v4 startup
and native account inventory in Strategy Manager; the receiver acknowledged it.
Copying remains off; no P01-to-Aqua trade was submitted for this validation.
See [setup and exact limits](MANUAL_COPYING.md). Docker was not live-validated.

## Earlier validation history

# Validation — September 9, 2026

- v2 session controls: **182 Python tests, 12 Vue tests, and 2 browser tests passed**.
  Production frontend build, lint, formatting and dependency checks passed.
  Tests cover exact JWT expiration, missing/malformed claims, expiry replacement,
  countdown expiration, browser-clock differences, same-account login refresh during
  capture, updated authentication headers on subsequent requests, and sanitized failures.
- Live v2 validation: two password logins and the subsequent active-orders read
  returned HTTP 200. The actual Vue Refresh token button also returned 200 and
  updated the displayed expiration. Capture remained running on account 123456;
  no browser errors occurred. Desktop and mobile screenshots were inspected.
  Private verification reports are in `data/token-validation/`.
- The following earlier v1 checks remain historical baseline evidence:
- Revalidated after relocation into `v1/`, using a fresh local virtual environment installed from the pinned dependencies. Python imported the package from `v1/src`; all 170 Python tests, all 8 Vue tests, the frontend production build and the isolated Chrome browser test passed from this location. Lint, formatting, dependency and CLI entry-point checks passed.
- All 19 endpoint fixture tests now assert the shared SDK User-Agent and both JSON headers. Handoff tests also assert the `matchtrader-python/v1/` archive prefix and file hashes.
- The running dashboard was moved to the v1 environment and reconnected to the same account. Existing credentials were preserved byte-for-byte; account exports and journals moved into `v1/data`. Shadow capture resumed after a recorded migration gap of approximately 112 seconds.
- Vue frontend: **8 unit tests passed**, production build passed. An isolated Chrome browser test passed for account selection, start/stop, fresh-ledger display and account switching. Desktop/mobile screenshots were inspected.
- Ruff lint and formatting checks passed; pip reports no broken dependencies; the CLI help smoke check passed.
- A distributable Python wheel built successfully with the standard isolated build workflow.
- Total Python statement coverage: **92%**. Every library module has a dedicated test file, enforced by a test. This includes the new local receiver/dashboard modules; it is not a live execution guarantee.
- Endpoint modules: all 19 covered with mocked HTTP method/path/payload/response assertions.
- Tests block real socket connections; no broker account, registration, trade, or WebSocket subscription was used.
- Shared REST ownership, concurrent acquisition, independent WebSocket singleton ownership, cleanup after exceptions, account selection, request pacing, cookie rotation, four-refresh-per-hour budget, and non-retry of mutations are tested.
- pandas/NumPy tests include timezone handling, invalid numeric input, partial-operation counting, breakevens, initial-loss drawdown, and avoiding parent/child exposure double counting.
- CLI snapshot test retrieves and exports seven data categories using fixtures and confirms credentials are not written into outputs.
- Pinned runtime dependencies resolved successfully for Linux x86-64 / Python 3.12 using pip's cross-platform dry-run mode. This is dependency resolution, not container execution.
- Docker/Compose build and runtime were **not executed**: Docker is not installed on this machine.
- Live AquaFunded check: an authenticated browser returned HTTP 200 JSON from `/manager/platform-details`; standalone HTTPX received HTTP 403 with `cf-mitigated: challenge`. This confirms a browser/client-session difference at the configured origin, not a failed credential check.
- Browser Closed Positions CSV export succeeded. This is a browser-assisted data retrieval, not verification of standalone SDK login/history access.
- Standalone SDK login, account token/session-cookie mapping, balance, active orders, open positions, and refresh were verified live on this VM. Each returned HTTP 200; the balance read after refresh also succeeded. Both order/position lists were empty, so populated-list parsing, history, instrument rules, trading mutations and the private WebSocket protocol remain deployment checks.
- Native curl confirmed the same User-Agent behavior: default identity returned 403; `hcamm-matchtrader/0.1.0` returned 200 for the same balance URL and authentication headers.
- After applying the identity fix, the running Vue dashboard's backend authenticated, discovered 14 accounts, refreshed active orders, and resumed its prior shadow capture state. Its short reload gap is recorded locally. No broker orders were submitted.
- Earlier HTTPX and curl.exe requests on this VM returned HTTP 403 with `cf-mitigated: challenge`. Subsequent Postman login on the same VM succeeded. Controlled balance reads isolated the User-Agent difference: HTTPX's default identity failed, while the SDK's own `hcamm-matchtrader/0.1.0` identity succeeded. The production client now sends that identity throughout the login/refresh/trading workflow. Single-slash paths and HTTP/1.1 work; HTTP/2 and a double-slash path alone did not resolve the failure.
- The owner also reports HTTP 200 for balance from host Postman using the platform origin, selected account system UUID/trading token, and top-level session cookie. A regression test verifies those mappings including account mismatch prevention. The SDK GET now includes both JSON headers. A subsequent VM balance check at 16:44 UTC returned a Cloudflare 403; the saved session's expiry claim was already past, so it was not a fresh-token comparison.
- Auth tests now cover `accounts`/`selectedAccount`, nested-token redaction, login field aliases, JSON/cookie refresh, account-token replacement, optional password-login renewal, the four-attempt budget and non-replay of mutations. Aqua keeps the documented refresh-cookie workflow as its default.
- Portable skill validation passed. Handoff tests check that credentials, private data, screenshots and caches are omitted and archive manifest hashes match contents.
- Reconciliation tests cover repeated-label ambiguity, changed brackets, quote touches, side/symbol/SL/TP matching, CSV total-row exclusion, duplicate IDs, timezone-less window rejection, source snapshots, and unknown send/receipt times.
- Bridge tests cover missing/invalid quantity, mandatory timezone, native order request shapes, unsupported STOP_LIMIT, wrong-account holds, stale revisions, durable duplicate detection, concurrent duplicate capture, EOF-only observation, partial CSV lines, truncation and no invented fills.
- Dashboard tests cover credential isolation, sanitized account discovery, active-order snapshots, connection failures, stopping/closing ownership, separate account journals, Host/origin checks, session authentication, request limits and path traversal rejection.
- The documented existing-user login and new-user registration/one-time-token sequence are verified with mocked transport. No live registration was performed.
- Local dashboard smoke check on the configured Aqua account: account selection rendered, Connect reported HTTP 403, shadow capture ran for 20 seconds with zero new ledger rows, and Stop returned capture to stopped. No broker orders were sent and Chrome reported no page errors. Private screenshots and the timestamped result are in `data/dashboard/` and excluded from handoff.

Commands:

```text
.venv/Scripts/python -m pytest -q
.venv/Scripts/ruff check src tests
.venv/Scripts/ruff format --check src tests
.venv/Scripts/python -m pip check
npm --prefix frontend test
npm --prefix frontend run build
# From frontend/, with Chrome installed:
npx playwright test
```

No percentage of mock-test coverage establishes live broker compatibility. Recipients should run the documented `platform` and `balance` reads after filling `.env` locally.

Multi-account validation covers simultaneous account sessions, separate account tokens/system routing, refresh-cookie isolation, per-account WebSockets, same-account reuse, different-broker isolation, and labeled DataFrames.
# v3 validation

See [V3_VALIDATION.md](V3_VALIDATION.md) for the current iteration's test results
and live-validation boundaries. The retained material below records earlier coverage.
