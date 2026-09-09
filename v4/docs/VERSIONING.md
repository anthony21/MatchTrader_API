# Current iteration: v4

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
