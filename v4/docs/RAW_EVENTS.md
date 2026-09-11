# Raw events (0.7.0)

Open **Raw events** in the dashboard sidebar. The authenticated browser event
stream delivers the newest 500 diagnostic messages, bounded additionally to 2 MiB
of serialized entries. Oldest entries roll off; the application restart clears
them. This buffer adds no SQLite rows or diagnostic files. Python and browser
object overhead is additional to the serialized payload budget.

Incoming authenticated WebSocket application messages are recorded before schema
validation, including hello and invalid JSON. Receiver ready and ACK/NACK replies
are shown separately. The monitor also includes authenticated native HTTP event
bodies and successful responses, labeled HTTP. It is not a packet sniffer:
upgrade headers, unauthenticated traffic, network Ping/Pong frames, and messages
rejected by the transport's frame-size limit are not captured. Binary content is
summarized. Credential fields and the configured sender token are redacted;
individual message previews are truncated at 32 KiB.

Search the JSON for X17, a symbol or an event ID. Expand a row to inspect it.
Pause freezes the display only; reception, routing and buffer rollover continue.
Resume returns to the current buffer. A slow browser can miss messages that roll
off before it receives a snapshot; this is diagnostic visibility, not an audit log.

## Disk storage

The raw monitor uses RAM only. The existing authoritative SQLite trade journal
still grows as valid events arrive. No journal retention/deletion policy is
introduced in this release: trade IDs, attempts and mapping evidence are needed
for duplicate prevention and recovery. Deleting that database is not a safe way
to clear the viewer. The separate C# sender may retain its own spool and receipts;
this page does not change those files.
