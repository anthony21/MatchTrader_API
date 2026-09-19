using System.Text.Json;

namespace HCAMM.QuantowerCapture;

public sealed record CaptureConfig
{
    public string Endpoint { get; init; } = "http://127.0.0.1:8765/capture/events";
    public string Outbox { get; init; } = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HCAMM", "QuantowerCapture", "outbox");
    public int MaxPending { get; init; } = 10000;
    public Dictionary<string, string> Sources { get; init; } = new();

    public static CaptureConfig Load(string path)
    {
        var config = JsonSerializer.Deserialize<CaptureConfig>(File.ReadAllText(path), CaptureEvent.Json)
            ?? throw new InvalidDataException("Missing capture configuration");
        config.Validate();
        return config;
    }

    public void Validate()
    {
        var uri = new Uri(Endpoint);
        if (uri.Scheme != "http" || !(uri.Host == "127.0.0.1" || uri.Host == "localhost") || uri.AbsolutePath != "/capture/events" || uri.Query != "" || uri.UserInfo != "")
            throw new InvalidDataException("Use the local capture endpoint");
        if (MaxPending is < 1 or > 100000 || !Path.IsPathFullyQualified(Outbox))
            throw new InvalidDataException("Invalid outbox configuration");
        if (Sources.Values.Any(v => v is not ("R01" or "X17" or "MANUAL" or "UNKNOWN")))
            throw new InvalidDataException("Invalid source attribution");
    }

    public string Source(string? sendingSource) => sendingSource != null && Sources.TryGetValue(sendingSource, out var source) ? source : "UNKNOWN";
}
