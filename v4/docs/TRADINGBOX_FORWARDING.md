# TradingBox forwarding (v4 0.8.2)

Copy settings has an independent **TradingBox signal forwarding** section:

| Forwarding | Live | Behavior |
| --- | --- | --- |
| Off | Off | Record incoming requests and return an explicit local receipt |
| On | Off | Preview/log only; zero upstream calls |
| On | On | Forward newly admitted requests to the configured TradingBox endpoint |

Turning forwarding off also clears Live. Both flags start off on every launch.
Only the destination URL is persisted in data/dashboard/tradingbox-forwarding.json.
The configured destination is editable only while off with no requests in flight.
Aqua API copying and the broker-profile connections are unchanged.

## Configure the sender

1. Add TB_FORWARD_API_KEY to the private v4 .env: use the same signal API key/header
   value already used by the indicator, not the PAMM read-only API key.
2. Set TB_FORWARD_AUTH_HEADER to X-HCAMM-Key (default), X-API-Key, or Authorization,
   matching the actual indicator. For Authorization, the configured value includes
   the original Bearer prefix if one is used. Keys never appear in dashboard responses.
3. Restart v4. In Copy settings, save the full upstream URL:
   https://tradingbox.pro/api/hcamm/events or https://tradingbox.org/api/hcamm/events.
   Use the original working TradingBox host. No default destination is silently chosen.
4. Point the indicator's TB endpoint to http://127.0.0.1:8765/api/hcamm/events and
   retain its original TradingBox authentication header/key. This replaces that
   indicator's direct path when using forwarding; do not also mirror the same trade
   signal directly to TradingBox, which could duplicate delivery.
5. Turn forwarding on for Preview; choose Go live with TradingBox for actual delivery.
   Live delivery may trigger TradingBox's configured trading actions.

A matching sender key is required even while off. Requests from browser Origin
contexts and unknown keys are rejected. Dashboard control APIs require the existing
same-origin session token. This patch does not import, configure, or start the old
port-8787 proxy. Native WebSocket events and /logging/events are not automatically
translated into TradingBox signals. The new route accepts original TB signal POSTs;
All HTTP routes under /api/hcamm/ now pass through, including GET /api/hcamm/commands
with its original query parameters and subsequent acknowledgement requests. Supported
methods: GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS. Keep any separately configured
X17 command/acknowledgement URLs on the same local origin, preserving their paths
and query strings. A URL still pointing directly at TradingBox bypasses this logger
and these controls. No calls or decisions are invented by the intermediary.

This is an HTTP application proxy, not a TLS impersonator or a WebSocket tunnel.
Other namespaces and connections X17 makes outside this local address are not
captured. Confirm any additional X17 endpoint paths from its sender configuration
before treating this as complete coverage of that indicator.

## Exact behavior and evidence

Requests accept bodies up to 1 MiB with Content-Length or chunked transfer framing.
Empty requests need no Content-Length. Ambiguous lengths, unsupported transfer
codings and request trailers are rejected rather than silently changed. No signal
schema, quantity, price, account, ID or timestamp fields are rewritten. Original
body bytes and end-to-end headers pass through. Host, Content-Length, connection
headers and TLS belong to the proxy's upstream connection. Normal HTTPS certificate
verification is enabled. Upstream status, reason, end-to-end response headers and
body return to the sender. HEAD/304 representation lengths and bodyless responses
are handled separately; duplicate response headers are preserved; redirects are returned, not followed by this service.
The sender itself controls whether it follows redirects or retries a failed request.

Before delivery, the request is durably logged. Request and response records share
metadata.cycle_id in the rolling observation archive and Event logging viewer.
Method and path are logged on both sides; query parameter values and authentication
headers are not archived. Original query strings are transmitted unchanged. Raw events shows new requests/replies.
Upstream replies are counted separately from uncertain delivery failures; an HTTP
success response is not proof of a broker fill.

Request logging failure prevents forwarding. Response logging failure after an
upstream reply preserves that reply and exposes response_log_failed in the status.
Transport failures return HTTP 502 with outcome uncertain; this service never retries
POSTs. Repeated incoming HTTP requests remain separate requests and may duplicate
upstream effects; retain the indicator's original event IDs and upstream deduplication.

Enabling forwarding does not replay archived requests. Eligibility is captured before
reading the request body and rechecked after its log commit, so changing controls
invalidates not-yet-admitted requests. Off blocks new admission immediately; an
already admitted network call can still finish. No cancellation or close is sent
for existing TradingBox trades when forwarding is disabled.

Response transport is bounded to 1 MiB. Larger responses produce an uncertain local
error. The archive retains up to 64 KiB per response with explicit original byte
count/truncation metadata. Request bodies above 64 KiB are likewise forwarded whole but archived only as an
explicitly marked prefix. Its existing 2,000-record / 8 MiB original-body rolling
limits apply, with SQLite overhead additional. New metadata columns migrate in
place; existing observation records remain valid. No executable trade journals
are deleted or repurposed.

Configuration endpoints: GET /api/tradingbox-forwarding; POST with exactly
{"url":"https://tradingbox.pro/api/hcamm/events","enabled":true,"live":false}.
These flags control forwarding only; there is no hidden change to payload live flags.

## Validation

Offline tests mimic X17 signal requests and command polls against a fake upstream,
including every supported method, exact query preservation, binary/chunked bodies,
authentication, duplicate headers, disabled forwarding, namespace escape rejection,
uncertain transport outcomes and bounded archive truncation. No synthetic signals
are sent to TradingBox. Actual end-to-end compatibility with the running X17 build
remains unverified until its traffic is directed through this endpoint.
