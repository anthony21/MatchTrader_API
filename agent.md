# Match-Trader API agent handoff

Current v3-base application authentication uses the broker registry described
in [SESSION_MANAGER.md](docs/SESSION_MANAGER.md). Its application session owner
supersedes the historical dashboard/account-owned login description below.
Preserve the SDK baseline; put session policies and validation above it.
Current Trading bridge ingress is the tokenless, always-on raw feed in
[LIVE_SIGNALS.md](docs/LIVE_SIGNALS.md); historical capture/copying UI instructions
below do not describe this signal page. Preserve broker authentication separately.
The application parsing engine is documented in [PARSING_ENGINE.md](docs/PARSING_ENGINE.md).
Its R01Signal model retains all 43 source fields; r01OrderShape projections are
stored with each newly received message for later operations.

This repository contains a Python client SDK, local shadow ingress, and a Vue dashboard. Help its owner install,
connect, retrieve account data, analyze it with pandas/NumPy, and package the SDK.
This is the `v3` application iteration. Run commands from this folder, and read
`docs/VERSIONING.md` before creating the next iteration.
Use the actual files and responses as evidence. Do not claim live compatibility
from mocked tests, browser access, or the presence of an endpoint in documentation.

## Start here

1. Read `README.md`, `docs/ENDPOINTS.md`, and `docs/VALIDATION.md` as needed.
   Use https://app.theneo.io/match-trade/platform-api/ as the primary reference
   for connection contracts, including its `/refresh-token` section. Distinguish
   documented behavior, user-supplied responses, and locally verified requests.
   Read `docs/FIRST_CONNECTION.md` for the implemented login/cookie/renewal workflow.
   Preserve the SDK's explicit User-Agent. On Aqua, the default HTTPX/curl identities
   received challenges while `hcamm-matchtrader/0.1.0` succeeded from the same VM.
2. Apply `.agents/skills/matchtrader-operations/SKILL.md` for operational work.
   This folder is portable. AI clients with repository skill discovery can load it;
   otherwise ask the AI to read its `SKILL.md` explicitly. Merely shipping markdown
   does not grant that AI desktop access, browser sessions, or broker credentials.
3. Locate `.env` without printing its contents. Check for Windows `.env.txt`
   naming mistakes. Never overwrite an existing credentials file with the example.
4. Install from `requirements.lock` into a virtual environment, then install this
   project with `pip install --no-deps -e .`. See README for Docker alternatives.
5. Run offline tests before changes, or the relevant checks after changes. Use
   `python -m pytest` and `ruff check src tests scripts`. Add a meaningful test for
   each new library module; `test_module_coverage.py` enforces module coverage.

## v3 native capture

Read `docs/QUANTOWER_CAPTURE.md`. Native C# events use a separate contract and durable
journal. Preserve trade IDs and uncertainty holds across CSV rollover and restarts.
Do not infer manual source from an empty SendingSource or convert futures quantities
to lots implicitly. Copying requires an explicit route and verified demo destination.
The legacy `/events` bridge and CSV observer remain preview-only. R01/X17 internal
signals need editable strategy publisher integration; the passive extension alone
does not see them. Keep `v1` and `v2` unchanged.

## Architecture to preserve

- `MatchTraderAPI` in `src/matchtrader/api.py` is the public facade.
- Each REST endpoint, request shape, and response entity has its own module.
- Services inherit the endpoint/service bases; data models use the independent
  Record/Request hierarchy and never create connections.
- REST and WebSocket use separate process-wide registries keyed by broker,
  login, and account. This is a singleton per account/transport, not one mutable
  global selected account. Use `for_account()` and explicitly close every owner.
- Credentials, cookies, token refresh state, and system IDs stay account-scoped.
  Never merge currencies or drop account provenance from combined analyses.
- The WebSocket transport is generic. A verified broker handshake/subscription
  adapter is still required. Do not invent one or treat REST paths as socket frames.
- The dashboard uses one controller and one shadow journal per selected account;
  it acquires broker connections through the existing account-scoped SDK registry.
  Stop capture before switching accounts. Frontend code must not contain broker
  credentials or call broker origins directly. Read `docs/DASHBOARD.md` and
  `docs/FIRST_CONNECTION.md` before changing the control plane or onboarding.
- The bridge only previews requests. Its SQLite ingress deduplication is not a
  live order lifecycle or broker idempotency mechanism. R01 CSV observations have
  no volume and are not executable order events. Do not claim the relay is replaced.

## Operational authorization

An instruction to connect, retrieve history, or compare trades permits relevant
read operations and local artifacts. It does not authorize placing, editing,
cancelling, copying, or closing trades. Keep writes disabled for these workflows.
Existing explicit authorization persists; do not repeatedly request permission
for necessary reads, local fixes, or packaging. Do not send reports to other people
or publish packages unless the user has requested that external action.

Do not execute unrelated live Quantower strategies, Telegram bots, watchdogs, or
relay publishers while investigating logs. Read source logs and preserve snapshots.
Do not change the user's running strategy or broker settings to make a comparison.

## Evidence and reporting

Label each stage precisely: strategy intent, quote touch, send attempt, relay
acknowledgement, broker order acceptance, fill, close. A quote touch is not a fill;
a send-to-fill interval is not network latency; missing logs do not prove no trade.
Record explicit time bounds, timestamp timezone evidence, account, currency,
source paths/row numbers, matching tolerances, and unresolved candidates.

Keep credentials, authentication headers, browser storage, unredacted HARs, account
exports, and private reports out of the handoff. `data/` is local and ignored.
Only `.env.example` with placeholders belongs in a distribution.

## Ship a reviewable handoff

Run `python scripts/build_handoff.py --output dist/matchtrader-v3-handoff.zip`.
The archive contains allowlisted source, tests, docs, dependency locks, container
files, and these agent/skill instructions. It excludes `.env`, data, local logs,
screenshots, browser profiles, caches, and the virtual environment. Inspect the
manifest and report tests and unresolved live/Docker validation honestly.

The recipient must supply their own terminal URL, credentials, and account IDs.
They should start with `matchtrader platform`, then an account-specific balance
read. A fresh AI may need browser/desktop tools connected separately.
