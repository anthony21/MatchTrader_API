# TradingBox relay logs in the local MatchTrader API

The relay listens at `http://127.0.0.1:8787`. Point the robots' event endpoint to
`http://127.0.0.1:8787/api/hcamm/events`. Existing command-poll paths also pass
through. Requests continue to the configured TradingBox upstream with the robot's
existing authentication headers. This integration does not read `ai-key.json` or
invent a PAMM API endpoint. Local log shipping uses the private MTR_BRIDGE_TOKEN.

The collector sends every byte of every `.log` and `.jsonl` file in the configured
relay logs directory to `POST http://127.0.0.1:8765/relay/logs`. It imports existing
files from offset zero and follows new bytes. Unknown event types, arbitrary JSON
fields, malformed/non-JSON lines, startup messages and upstream failures are archived.
Original request/response bodies are additionally recorded as base64 before the
client reply; original request bytes are fsynced before contacting the upstream.
Known authentication headers are omitted from relay logs. Application data is private.

## Storage and viewing

- Durable archive: `MatchTrader_API/v4/data/dashboard/relay/relay.sqlite3`.
- Collector replay checkpoints/pending chunks: `relay/delivery/collector.sqlite3`.
- Dashboard **Raw events** shows new chunks labeled `tradingbox-relay`. This is a
  bounded live preview, not the complete archive; large messages may span chunks.
- `GET /api/relay/logs?after=0` uses the dashboard's existing X-Session-Token auth.
  It returns up to 100 chunks and `next_after`; page until no records remain.
  Each record contains filename, machine, stream ID, byte offset, receipt time,
  SHA-256 and `data_base64`. Decode and concatenate chunks within each stream by
  byte offset to recover the complete original file. Request IDs join the raw
  request, response, and parsed summary records; these are different log views.
- `GET /api/status` includes durable relay chunk/byte/stream counts.

No schema filter maps these logs to executable trades. No broker order or copying
action is performed by relay ingress, even if a raw log says ACCEPTED/CREATE.

## Recovery and limits

The sender persists each exact chunk before transmission. It advances its file
cursor only after a matching durable ACK. The receiver uses SQLite FULL commits,
contiguous offsets, checksums and persistent deduplication. Lost ACKs replay the
same bytes, including when the source file grows before reconnection. Log files
are never removed by the collector; the archive has no automatic retention limit.

The collector retries local receiver outages with backoff. It must retain its
state database and source files. Deleting/overwriting an unread source file,
disk failure/full storage, or events the robots never publish can still prevent
capture. There is no honest universal 100% guarantee. Changing a file's identity,
prefix, or truncating below its read cursor starts a new stream. Do not run two
collectors against the same state file or manually truncate active logs.

The original relay does not automatically retry upstream POSTs; adding such retries
could duplicate upstream actions. The local log collector never reissues a robot
request to TradingBox. Forwarded upstream 403/502 responses remain upstream failures,
even when their logs have been durably received locally.

## Run

From `relay/`: `python -u tb-relay.py`.

From `MatchTrader_API/v4/`, with its virtual environment:

```powershell
.venv/Scripts/python.exe -u -m matchtrader.capture.relay_collector --logs ../../relay/logs --state ../../relay/delivery/collector.sqlite3 --env .env
```

For the actual sibling layout shown here, use absolute paths or `../..` relative
to `v4` (both projects live beneath CuatroCubed). The dashboard must be running
with the updated server. Collector stdout/stderr belongs outside the relay's source
log directory, preventing it from ingesting its own delivery diagnostics.

Services launched for this session run hidden; automatic startup after a Windows
reboot is not configured. Restart the collector with the same state file to resume.

Validation: 296 Python checks passed across the suite and the rerun of missing
fixture-dependent tests; Ruff passed. A real isolated relay -> collector -> dashboard
HTTP test preserved a 21KB unfamiliar event and all four resulting log files exactly,
with TradingBox forwarding disabled and zero trade-dispatch events.
