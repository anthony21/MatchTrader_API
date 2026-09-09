using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace HCAMM.QuantowerCapture;

public sealed class DurableOutbox : IDisposable
{
    readonly CaptureConfig config;
    readonly object gate = new();
    readonly HttpClient client;
    readonly CancellationTokenSource stop = new();
    Task? worker;
    long sequence;
    public Action<CaptureEvent, string, string, string>? Acknowledged { get; set; }
    public string Health { get; private set; } = "Ready";

    public DurableOutbox(CaptureConfig config, HttpMessageHandler? handler = null)
    {
        config.Validate();
        this.config = config;
        Directory.CreateDirectory(config.Outbox);
        sequence = Directory.EnumerateFiles(config.Outbox, "*.json").Select(p => long.TryParse(Path.GetFileName(p).Split('-')[0], out var n) ? n : 0).DefaultIfEmpty(0).Max();
        client = new HttpClient(handler ?? new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false });
        client.Timeout = TimeSpan.FromSeconds(10);
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", config.Token);
    }

    public void Enqueue(CaptureEvent item)
    {
        lock (gate)
        {
            if (Directory.EnumerateFiles(config.Outbox, "*.json").Take(config.MaxPending).Count() >= config.MaxPending)
            {
                Health = "Outbox full: capture fault; copying must be stopped";
                throw new IOException(Health);
            }
            // Persist before returning to Qt. HTTP never runs in the callback.
            var name = Path.Combine(config.Outbox, $"{++sequence:D20}-{Guid.NewGuid():N}.json");
            var bytes = JsonSerializer.SerializeToUtf8Bytes(item, CaptureEvent.Json);
            using (var file = new FileStream(name + ".tmp", FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { file.Write(bytes); file.Flush(true); }
            File.Move(name + ".tmp", name);
        }
    }

    public void Start() => worker ??= Task.Run(async () =>
    {
        while (!stop.IsCancellationRequested)
        {
            try { if (!await PumpOnce(stop.Token)) await Task.Delay(250, stop.Token); }
            catch (OperationCanceledException) when (stop.IsCancellationRequested) { break; }
            catch { Health = "Delivery unavailable; persisted events retained"; try { await Task.Delay(2000, stop.Token); } catch (OperationCanceledException) { break; } }
        }
    });

    public async Task<bool> PumpOnce(CancellationToken cancellationToken = default)
    {
        string? path;
        lock (gate) path = Directory.EnumerateFiles(config.Outbox, "*.json").Order().FirstOrDefault();
        if (path == null) return false;
        var raw = await File.ReadAllTextAsync(path, cancellationToken);
        using var response = await client.PostAsync(config.Endpoint, new StringContent(raw, Encoding.UTF8, "application/json"), cancellationToken);
        if ((int)response.StatusCode != 202) { Health = $"Receiver HTTP {(int)response.StatusCode}; outbox retained"; return false; }
        using var ack = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
        using var sent = JsonDocument.Parse(raw);
        if (ack.RootElement.GetProperty("event_id").GetString() != sent.RootElement.GetProperty("event_id").GetString())
            throw new InvalidDataException("Mismatched acknowledgement");
        lock (gate) File.Delete(path);
        Health = "Connected; latest event acknowledged";
        string Field(string name) => ack.RootElement.TryGetProperty(name, out var field) ? field.GetString() ?? "" : "";
        // A UI logging failure must never retry a broker-acknowledged event.
        try { Acknowledged?.Invoke(JsonSerializer.Deserialize<CaptureEvent>(raw, CaptureEvent.Json)!, Field("status"), Field("reason"), Field("broker_order_id")); } catch { }
        return true;
    }

    public void Dispose()
    {
        stop.Cancel();
        try { worker?.GetAwaiter().GetResult(); } catch (OperationCanceledException) { }
        client.Dispose(); stop.Dispose();
    }
}
