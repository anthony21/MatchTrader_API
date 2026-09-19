using System.Net;
using System.Text.Json;
using HCAMM.QuantowerCapture;
using TradingPlatform.BusinessLayer;

var passed = 0;
void Check(bool condition, string name) { if (!condition) throw new Exception(name); Console.WriteLine("PASS " + name); passed++; }
var directory = Path.Combine(Path.GetTempPath(), "hcamm-capture-test-" + Guid.NewGuid().ToString("N"));
var config = new CaptureConfig { Outbox = directory,
    Sources = new() { ["HCAMM:R01"] = "R01", ["verified-manual"] = "MANUAL" } };
config.Validate();
Check(config.Source(null) == "UNKNOWN" && config.Source("HCAMM:R01") == "R01", "CaptureConfig exact attribution");
try { (config with { Endpoint = "https://external.example/capture/events" }).Validate(); throw new Exception("accepted external URL"); }
catch (InvalidDataException) { Check(true, "CaptureConfig refuses external token recipient"); }
var item = new CaptureEvent { EventId = "test-event", ConnectionId = "source", AccountId = "account", Kind = "ACCEPTED", Action = "CREATE", Quantity = .01m };
using (var doc = JsonDocument.Parse(JsonSerializer.Serialize(item, CaptureEvent.Json)))
    Check(doc.RootElement.GetProperty("quantity").GetDecimal() == .01m && doc.RootElement.GetProperty("event_id").GetString() == "test-event", "CaptureEvent wire schema");
using (var outbox = new DurableOutbox(config)) outbox.Enqueue(item);
Check(Directory.GetFiles(directory, "*.json").Length == 1, "DurableOutbox survives owner shutdown");
var attempts = 0;
using (var outbox = new DurableOutbox(config, new FakeHandler(async request => {
    var body = await request.Content!.ReadAsStringAsync();
    Check(request.Headers.Authorization is null, "DurableOutbox requires no sender authentication");
    attempts++;
    return new HttpResponseMessage(attempts == 1 ? HttpStatusCode.ServiceUnavailable : HttpStatusCode.Accepted)
        { Content = new StringContent("{\"event_id\":\"test-event\"}") };
}))) {
    Check(!await outbox.PumpOnce() && Directory.GetFiles(directory, "*.json").Length == 1, "DurableOutbox retains unacknowledged event");
    Check(await outbox.PumpOnce() && Directory.GetFiles(directory, "*.json").Length == 0, "DurableOutbox removes only acknowledged identity");
}
using (var outbox = new DurableOutbox(config with { MaxPending = 1 })) {
    outbox.Enqueue(item);
    try { outbox.Enqueue(item); throw new Exception("overflow ignored"); }
    catch (IOException) { Check(outbox.Health.Contains("full"), "DurableOutbox reports capacity fault"); }
}
Check(!CapturePublisher.PublishSignal(item with { Source = "R01" }), "CapturePublisher reports detached extension");
Check(NativeObserver.OrderKind(OrderTypeBehavior.StopLimit) == "STOP_LIMIT" && NativeObserver.OrderKind(OrderTypeBehavior.TrailingStop) == "UNKNOWN", "NativeObserver preserves unsupported types");
Check(typeof(CaptureStrategy).IsSubclassOf(typeof(Strategy)) && typeof(CaptureStrategy).GetField("Configuration") != null, "CaptureStrategy matches installed extension contract");
Console.WriteLine($"{passed} checks passed. No broker or Qt Core calls made.");

sealed class FakeHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> send) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => send(request);
}
