# Logging-only ingress (v4 0.7.1)

Send a copy of each observation to `POST http://127.0.0.1:8765/logging/events`
with `Authorization: Bearer <MTR_BRIDGE_TOKEN>` and the original content type/body.
JSON of any schema, unknown event kinds, text and binary bodies up to 64 KiB are
accepted. Empty bodies are recorded. Invalid authentication, incomplete bodies and
oversized messages are refused. This endpoint works independently of Start capture.

HTTP 202 reports a unique receipt_id, durable:true, forwarded:false, executed:false.
It confirms a local FULL SQLite commit, not TradingBox delivery or a broker action.
Repeated deliveries produce separate receipts; this is a log, not execution deduplication.
Use Raw events for immediate ingress/reply previews and Event logging for saved history.
GET /api/logging/events?before=0 uses dashboard session authentication and returns
100 newest records plus next_before. The browser receives redacted previews only.

The private archive is data/dashboard/logging/observations.sqlite3. Original bytes,
SHA256, receipt timestamp and content type are retained. Authentication headers are
not stored. Up to 2,000 records and 8 MiB of original bodies are retained; older
observations are deleted automatically. SQLite index/WAL overhead is additional;
freed pages are reused rather than shrinking the file on every write. This policy
applies only to this new observation archive, not trade identities or legacy relay logs.

Inspired by x.0.1 logging: preserve opaque bodies and distinguish local receipts
from upstream decisions. No proxy, launcher, shutdown, command polling or execution
capabilities were copied. Keep the sender's existing TradingBox destination and
mirror observations here. Do not replace a production TradingBox endpoint with this
logging-only endpoint expecting forwarding. A TB-only sender still needs dual-output
support or the existing external relay/log collector to reach both destinations.
