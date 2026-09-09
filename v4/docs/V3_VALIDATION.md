# v3 validation — September 9, 2026

Implemented in `v3`, preserving the v1/v2 source folders.

- Python: 208 tests passed. Every library module has a dedicated test file.
- Vue: 15 tests passed; production bundle built.
- Browser: three Chrome tests passed, including desktop/mobile Orders navigation.
- C#: compiled against installed Quantower 1.146.18, .NET 10; 12 offline checks passed.
- Ruff: clean.

The C# extension was installed, added to Quantower Strategies manager and started.
Actual account inventory reached the Python receiver and was acknowledged; the
outbox drained. This was repeated after updating/restarting the extension.
The native account snapshot identifies the connected cTrader account. No synthetic
order was sent into the running receiver as a substitute for a native trade test.

The v3 dashboard replaced the v2 process on loopback port 8765 after stopping its
observer and copying a consistent SQLite backup. A fresh Aqua login succeeded;
pending-order and open-position reads succeeded for account 123456, both empty at
the time of verification. A separate headless browser verified the native account
row and successful HTTP responses from both Orders-page refresh actions.

Copying is **disarmed** and no route file has been configured. No broker trade was
created, edited, cancelled or closed by this v3 validation. The user still needs
to specify source-account selection and instrument sizing. R01/X17 internal signals
require publisher hooks in their editable C# projects; only installed binaries
were located. Exact Aqua position relationships need a controlled fill test before
claiming full end-to-end position management. See QUANTOWER_CAPTURE.md for holds.

The CSV is a bounded view over the durable database. Its rollover and restart
deduplication are unit-tested. Live CSV currently reflects only identities actually
observed; account snapshots do not invent trade rows.

Docker was not run on this VM. Quantower remains a Windows desktop process and
must stay awake. The source handoff excludes .env, private runtime data, outbox
tokens, compiled DLLs, build caches and proprietary Quantower assemblies.
