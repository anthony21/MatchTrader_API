# Handoff to the Quantower C# sender session

Implement the sender side of QUANTOWER_WEBSOCKET_PLAN.md transport 1.0.0 against
capture-event-1.1.0.json. Share both files with this session. The Python receiver is implemented in application 0.5.0; see
QUANTOWER_WEBSOCKET_RECEIVER.md for launch and capture controls. Do not assume the dashboard SSE stream receives Quantower events.

Deliver WebSocketCaptureTransport plus explicit config selection, reusing the
existing durable outbox and stable event IDs. Wake immediately after persistence
instead of waiting 250 ms. Connect to ws://127.0.0.1:8767/capture/ws with subprotocol
hcamm.capture.v1 and Authorization Bearer using the existing private bridge token.
Implement hello/ready, event envelopes, correlated durable terminal ACKs, permanent
NACK quarantine, retryable NACK backoff, bounded pipelining, Ping/Pong and reconnect.
Keep one SendAsync loop and one ReceiveAsync loop, both off Quantower callbacks.

Follow the shared plan exactly for sizes, versions, message examples, machine
identity, max_inflight, outbox deletion, replay and ordering. Do not invent separate
wire fields or turn FILL/SIGNAL/REQUEST observations into new executable orders.
Do not send Aqua credentials, round decimals, infer unknown strategy identity,
replace IDs on retry, or simultaneously use HTTP and WebSocket delivery.

Return changed source, dedicated module tests, C# build results, example config
with placeholders, and a fake-receiver interoperability test. State untested
Quantower runtime behavior explicitly. Do not deploy into the running terminal or
turn on trade copying. The receiver is implemented in the Python workspace; use its setup document for the running endpoint.

The under-10-ms objective is receiver complete-message arrival to outbound HTTP
transport write start. Sender callback/outbox/send timing is measured separately.
A WebSocket alone cannot meet the objective: current receiver pacing and broker
preflight reads also require measured optimization. Keep durable replay protection.
