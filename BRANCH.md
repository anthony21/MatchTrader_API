# v3 restructure branch

Created September 18, 2026 at the user's request.

- Working folder: `C:/HCAMM/matchtrader-python/v3-base`
- Git branch: `v3-restructure`, in the `v3-base` linked worktree; the original worktree stays on `main`.
- Branch origin: `v3-base`, preserving the original v3 source and verified order baseline.
- Baseline commit: `6448ce8`, using the original repository's preserved `v3` tree.
- Historical source import: `ff3f836`.
- Application/package version: `0.1.0`.

This is the preserved v3 implementation as a fresh starting point. It contains the
core MatchTrader SDK and CLI, along with v3's basic Vue dashboard, shadow bridge,
and Quantower native capture. No later v4 P01 signal engine, R01 configuration
lanes, or 5.0.0 features were carried over. No features have been removed yet.

The source baseline matches the preserved v3 Git tree. Original v1, v2, v3 and v4
folders were not changed. w4 was stopped and removed; its local journals were
retained in `../v4/data/retired-w4-20260918/data`.

No credentials, live journals or virtual environment were imported into this
branch. No application is started by creating it. When setting up this branch,
run commands here and create its own environment; historical references to the
folder name v3 refer to this baseline's origin.

Validation: 113 offline core/API/endpoint/model/CLI tests passed, using the existing
v4 Python environment with imports explicitly directed to this branch's `src`.
No broker connection or order was made for this validation.

## Runtime started September 18, 2026

At the user's subsequent request, this branch now has its own `.venv`, local v3
connection settings, frontend dependencies, and a freshly built dashboard.
These runtime additions are ignored by Git. No live journals were imported.
The dashboard runs at http://127.0.0.1:8765 and returned HTTP 200. Its Python
module path was verified as `v3-base/src/matchtrader`. Capture and copying start
off, and the broker remains disconnected. Logs are in `data/runtime/`.

## Application session layer

The application now uses a broker-keyed session manager with independent token
caches, account handles, asynchronous broker HTTP pools, and background renewal
scheduled three minutes before expiry. See [SESSION_MANAGER.md](docs/SESSION_MANAGER.md).
The base SDK facade, core, endpoint implementations and request/response models
remain unchanged from the verified pending-order baseline.

The async pools default to 24 connections for 16 expected concurrent requests,
15-second keep-alive expiry, and a 1.5-second connection timeout. See
[ASYNC_TRANSPORT.md](docs/ASYNC_TRANSPORT.md) for per-broker configuration and
the SDK compatibility boundary. Verification: 246 offline/local Python tests
passed; the unchanged SDK paths have no diff against the saved baseline.

Trading bridge now shows an always-on raw signal feed. WebSocket publishers use
`ws://127.0.0.1:8766/signals`; HTTP publishers use
`http://127.0.0.1:8765/signals`. No bridge token is required. These endpoints only
journal and display signals, independent of broker connections or capture state.
See [LIVE_SIGNALS.md](docs/LIVE_SIGNALS.md) for payloads and compatibility aliases.

## Restructure checkpoint

The application parses each R01 event into its complete 43-field source model and
produces named order shapes for later operations. The live Trading bridge expands
batches into rows, filters by sender/machine/event, and provides a column-header
filter with group-to-field navigation for every schema field. Column choices
persist in the browser. See [PARSING_ENGINE.md](docs/PARSING_ENGINE.md).

Validation for this checkpoint: 278 Python tests, 28 frontend tests, Ruff, and the
production frontend build passed. Browser checks used live R01 data and verified
filters, column selection, persistence, keyboard behavior, and mobile layouts.
The C# sender source was updated, but this environment's .NET installation has no
SDK, so that build remains unverified.
