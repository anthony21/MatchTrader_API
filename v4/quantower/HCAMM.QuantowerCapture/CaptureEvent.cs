using System.Text.Json;

namespace HCAMM.QuantowerCapture;

public sealed record CaptureEvent
{
    public int SchemaVersion { get; init; } = 1;
    public string EventId { get; init; } = Guid.NewGuid().ToString("N");
    public string Machine { get; init; } = Environment.MachineName;
    public string ConnectionId { get; init; } = "unknown";
    public string AccountId { get; init; } = "unknown";
    public string OrderId { get; init; } = "";
    public string PositionId { get; init; } = "";
    public string ExecutionId { get; init; } = "";
    public string RequestId { get; init; } = "";
    public DateTimeOffset EmittedAt { get; init; } = DateTimeOffset.UtcNow;
    public string Kind { get; init; } = "ORDER";
    public string Action { get; init; } = "OBSERVE";
    public string Source { get; init; } = "UNKNOWN";
    public string SourceLabel { get; init; } = "";
    public string SendingSource { get; init; } = "";
    public string Status { get; init; } = "";
    public bool Snapshot { get; init; }
    public string Symbol { get; init; } = "";
    public string Side { get; init; } = "";
    public string OrderType { get; init; } = "UNKNOWN";
    public decimal Quantity { get; init; }
    public decimal Price { get; init; }
    public decimal Sl { get; init; }
    public decimal Tp { get; init; }
    public bool BracketsAbsolute { get; init; } = true;
    public static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
}
