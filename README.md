# Match-Trader versions

Current release: **0.8.2**. **[Complete installation and operating instructions](v4/docs/SETUP.md)**
cover installation, X17/TradingBox forwarding, five separate broker profiles,
logging, troubleshooting and validation. The separate `x.0.1` workspace is excluded
from Git and the v4 source handoff.

The current application lives in [v4](v4/README.md). It adds native Quantower capture,
persistent trade IDs, a rolling CSV and the Orders workspace page. v1, v2 and v3 remain
preserved. Read [capture setup](v4/docs/QUANTOWER_CAPTURE.md) before configuring copying.

Run installation, tests, CLI commands and Docker Compose from that folder:

```powershell
Set-Location .\v4
poetry install
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
# Create and configure .env using the setup guide before starting.
poetry run python -m matchtrader.dashboard.cli
```

The dashboard is available at http://127.0.0.1:8765 when running. Its credentials
are in `v4/.env`; active journals are in `v4/data/`. Earlier exports and original
journals remain in `v1/data/`.

See [versioning](v4/docs/VERSIONING.md) before starting the next iteration.
The next iteration should use a separate version folder based on the tested v4
source bundle. Keep credentials and runtime data separate between versions.

## Public source checkout

This repository contains source, tests and setup documentation for v1?v4. The
Python API, Vue dashboard and Quantower C# extension are in v4. Credentials, trade
exports, live journals, compiled binaries and local dependencies are excluded.
Copy v4/.env.example to v4/.env and supply your own broker credentials. Account
identifiers in historical documentation are placeholders. See v4/README.md for
installation and v4/docs/MANUAL_COPYING.md for the current integration limits.

GitHub stores this source; the running API and Quantower strategy still require
a machine or VM. Publishing this repository does not move the running services.
