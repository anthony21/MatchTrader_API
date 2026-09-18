# v3 baseline branch

Created September 18, 2026 at the user's request.

- Working folder: `C:/HCAMM/matchtrader-python/v3-base`
- Git branch: `v3-base`, a separate linked worktree; the original worktree stays on `main`.
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
