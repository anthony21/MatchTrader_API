// Test-only ClientWebSocket peer. Never point it at an armed production receiver.
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;

if (args.Length != 2) throw new ArgumentException("Expected test receiver URL and test token");
using var socket = new ClientWebSocket();
socket.Options.AddSubProtocol("hcamm.capture.v1");
socket.Options.SetRequestHeader("Authorization", "Bearer " + args[1]);
using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
await socket.ConnectAsync(new Uri(args[0]), timeout.Token);
async Task Send(object message) => await socket.SendAsync(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(message)), WebSocketMessageType.Text, true, timeout.Token);
async Task<JsonElement> Receive() {
    using var body = new MemoryStream();
    var buffer = new byte[1024];
    WebSocketReceiveResult part;
    do {
        part = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), timeout.Token);
        if (part.MessageType != WebSocketMessageType.Text) throw new Exception("Expected text response");
        body.Write(buffer, 0, part.Count);
        if (body.Length > 32768) throw new Exception("Oversize response");
    } while (!part.EndOfMessage);
    return JsonDocument.Parse(body.ToArray()).RootElement.Clone();
}
await Send(new { type = "hello", transport_version = "1.0.0", event_schema_version = "1.1.0", machine = "qt", sender_instance_id = Guid.NewGuid().ToString() });
if ((await Receive()).GetProperty("type").GetString() != "ready") throw new Exception("Handshake failed");
string? tradeId = null;
foreach (var (action, index) in new[] { ("CREATE", 1), ("EDIT", 2), ("CANCEL", 3) }) {
    var message = new { type = "event", transport_version = "1.0.0", @event = new {
        schema_version = "1.1.0", event_id = $"smoke:{index}", machine = "qt", connection_id = "connection", account_id = "source",
        order_id = "order1", request_id = $"smoke-request:{index}", emitted_at = DateTimeOffset.UtcNow.ToString("O"),
        kind = "ACCEPTED", action, source = "MANUAL", symbol = "EURUSD", side = "BUY", order_type = "LIMIT",
        quantity = "1", price = "1.15000", sl = "1.14000", tp = "1.16000"
    }};
    await Send(message);
    var ack = await Receive();
    if (ack.GetProperty("type").GetString() != "ack" || !ack.GetProperty("durable").GetBoolean()) throw new Exception("Missing durable ACK");
    var result = ack.GetProperty("result");
    if (result.GetProperty("status").GetString() != "accepted") throw new Exception("Fake broker action wasn't accepted");
    var currentId = result.GetProperty("trade_id").GetString();
    tradeId ??= currentId;
    if (tradeId != currentId) throw new Exception("Trade identity changed");
    await Send(message);
    if (!(await Receive()).GetProperty("duplicate").GetBoolean()) throw new Exception("Replay wasn't deduplicated");
}
await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "Test complete", timeout.Token);
Console.WriteLine("C# contract smoke passed: hello, create/edit/cancel, durable ACKs, stable trade ID and replay.");
