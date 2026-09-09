using System.Text.Json;

namespace HCAMM.QuantowerCapture;

public sealed record CaptureConfig
{
    public string Endpoint { get; init; } = "http://127.0.0.1:8765/capture/events";
    public string Token { get; init; } = "";
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
        if (Token.Length < 32 || Token.Any(c => c > 127 || char.IsWhiteSpace(c)))
            throw new InvalidDataException("Configure a private sender token");
        if (MaxPending is < 1 or > 100000 || !Path.IsPathFullyQualified(Outbox))
            throw new InvalidDataException("Invalid outbox configuration");
        if (Sources.Values.Any(v => v is not ("R01" or "X17" or "MANUAL" or "P01" or "UNKNOWN")))
            throw new InvalidDataException("Invalid source attribution");
    }

    public string Attribute(string? sendingSource, string? comment)
    {
        // A named strategy always takes precedence; blank source alone is never manual.
        var source = Source(sendingSource);
        if (source != "UNKNOWN") return source;
        return System.Text.RegularExpressions.Regex.IsMatch(comment ?? "", @"^P01RR_[0-9]{6}_[0-9]+$") ? "P01" : "UNKNOWN";
    }

    public string Source(string? sendingSource) => sendingSource != null && Sources.TryGetValue(sendingSource, out var source) ? source : "UNKNOWN";
}
