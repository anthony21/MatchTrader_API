# v2: session expiration controls

This iteration adds token expiration metadata, the Vue countdown and a manual
login refresh action using the existing connection. The v1 source remains preserved
in the sibling folder. The existing endpoint/service/model layout is unchanged.

This folder is derived from the verified v1 source bundle, established September 9,
2026. The Python distribution and Vue package remain `0.1.0`; `v2` names the
application baseline. Python imports remain `from matchtrader import ...`.

The application root is `C:\HCAMM\matchtrader-python\v2`. Source, tests, frontend,
Docker configuration, agent instructions and dependency locks all live here.
The local `.venv` was rebuilt from the pinned dependencies at this location.
Credentials are in `.env`, and private account exports and journals are in `data/`.
These local files are excluded from the source bundle.

## Connection behavior to preserve

All REST endpoints use the shared `RestConnection`. It sends
`User-Agent: hcamm-matchtrader/0.1.0`, `Accept: application/json`, and
`Content-Type: application/json`. Endpoint tests assert these headers across all
19 REST endpoints. A separate regression covers login, refresh and trading reads.
This is the configuration that returned HTTP 200 from Aqua on this VM; future
responses still depend on valid credentials, permissions and broker availability.

Use the configured platform origin and canonical single-slash endpoint paths.
Trading requests use the chosen account's system UUID and trading token, with the
top-level login token as `co-auth`. Preserve the account-scoped cookie jar for
refresh and account isolation. See [first connection](FIRST_CONNECTION.md).

## Reproduce this baseline

From this folder, run the checks in [VALIDATION.md](VALIDATION.md). Build the
portable snapshot with:

```powershell
.venv/Scripts/python scripts/build_handoff.py --output dist/matchtrader-v2-handoff.zip
```

The ZIP contains `matchtrader-python/v2/` and a SHA-256 manifest for the included
source files. Save this bundle before starting the next iteration.

## Next iteration

Create a separate version folder from the validated source bundle. Recreate its
Python environment, install its frontend dependencies, and configure a local
`.env` explicitly. Update that iteration's archive prefix, documentation, and
version metadata before release. Keep `v1`, `v2`, and their source bundles available for
comparison and rollback. Run only one ledger observer on the same source unless
parallel observation is deliberately configured; journals belong to each version.

This folder layout does not create a Git branch or tag. Git version control can
be added separately. Testing additional live endpoints belongs to the next work
stage; the current live coverage is recorded in `VALIDATION.md`.
