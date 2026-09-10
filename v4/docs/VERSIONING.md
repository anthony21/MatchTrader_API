# Current release: 0.6.0 (workspace v4)

Use semantic `major.minor.patch` releases from this point onward. Breaking contracts
increment major; compatible features increment minor; compatible fixes increment patch.
Workspace folders are independent of release versions: current development stays in v4.
Event and journal contracts have independent schema versions. See
[trade mapping 0.2.0](TRADE_MAPPING.md) for event schema 1.1.0 and mapping schema 1.0.0.
Python/frontend package versions and `matchtrader.version.VERSION` must agree.

See [the changelog](CHANGELOG.md) for readable release summaries and the Git tag
policy. The first tagged release is 0.6.0; earlier entries below are local
development milestones included in that release, not separately published tags.

## 0.6.0 - readable Orders workspace

React trade cards, position/pending/copy activity tabs, expandable references,
strategy search, review filtering and pagination. Mapping summaries add recorded
instrument/side/source context. See [Orders workspace](ORDERS_WORKSPACE.md).

## 0.5.0 - Quantower WebSocket receiver

Native capture transport 1.0.0 adds a loopback receiver, durable terminal ACKs,
bounded dispatch queues, sender health and transport timing. Event schema remains
1.1.0. CSV export moves off the dispatch path. See
[receiver setup](QUANTOWER_WEBSOCKET_RECEIVER.md).

## 0.4.0 — native event push

Authenticated SSE replaces native-feed polling while connected. Reconnects reload
the durable journal snapshot; other control and broker snapshot cadences remain
unchanged. See [incoming trade stream](INCOMING_TRADES.md#live-push-040).

## 0.3.0 — incoming trades workspace

The incoming feed now uses React with source/account filters, separate lifecycle
columns and backend event meanings 1.0.0. Existing event and mapping schemas remain
compatible. See [incoming trades](INCOMING_TRADES.md).

## Historical folder iterations

v4 was created from the verified v3 source handoff. Preserve v1, v2 and v3.
Use the tested v4 source handoff as the basis for v5. Private environments and
journals are excluded from bundles. Migrate live journals with SQLite backup.

# v3: native Quantower capture

Derived from the verified v2 source bundle on September 9, 2026. v1 and v2 remain
unchanged. All active source, tests, configuration and dependencies live in this
folder. The Python import name and REST User-Agent remain unchanged; application
iteration folders are separate from the 0.1.0 package version.

v3 adds C# native event capture, persistent trade IDs, bounded CSV export,
explicit demo routing and the Orders sidebar page. Read QUANTOWER_CAPTURE.md for
setup, supported actions and the limits of source/position attribution.

Build the handoff with `python scripts/build_handoff.py`. Its archive prefix is
`matchtrader-python/v3/`; a SHA-256 manifest covers all included source files.
Credentials, private data, compiled assemblies and node_modules are excluded.
Rebuild the C# extension against the recipient's installed Quantower BusinessLayer.

Before the next iteration, save this validated source bundle. Create a new version
folder and its own environment; preserve the trade journal when switching an
existing route. Do not run duplicate observers or routers against the same source.
