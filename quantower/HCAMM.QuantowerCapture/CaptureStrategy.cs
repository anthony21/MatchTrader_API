using TradingPlatform.BusinessLayer;

namespace HCAMM.QuantowerCapture;

public sealed class CaptureStrategy : Strategy
{
    static int active;
    DurableOutbox? outbox;
    NativeObserver? observer;
    bool owns;

    [InputParameter("Capture configuration file", 0)]
    public string Configuration = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HCAMM", "QuantowerCapture", "capture.json");

    public CaptureStrategy() { Name = "HCAMM Quantower Capture v3"; Description = "Native order/position observer. Broker routing is controlled in the local dashboard."; }

    protected override void OnRun()
    {
        if (Interlocked.CompareExchange(ref active, 1, 0) != 0) throw new InvalidOperationException("Only one capture instance may run");
        owns = true;
        try
        {
            var config = CaptureConfig.Load(Configuration);
            outbox = new DurableOutbox(config);
            observer = new NativeObserver(config, Capture, () => Log("CAPTURE FAULT: native callback could not be read. Stop copying and inspect Quantower.", StrategyLoggingLevel.Error));
            observer.Start();
            CapturePublisher.Attach(Capture);
            outbox.Start();
            Log("Native capture attached. Copying is controlled by the dashboard.");
        }
        catch { OnStop(); throw; }
    }

    void Capture(CaptureEvent item)
    {
        try { outbox?.Enqueue(item); }
        catch { Log("CAPTURE FAULT: event could not be persisted. Stop copying and inspect the local outbox.", StrategyLoggingLevel.Error); }
    }

    [Obsolete("Quantower retains this hook for legacy strategy metrics")]
    protected override List<StrategyMetric> OnGetMetrics() => new() { new StrategyMetric { Name = "Capture delivery", FormattedValue = outbox?.Health ?? "Stopped" } };

    protected override void OnStop()
    {
        if (!owns) return;
        CapturePublisher.Attach(null);
        observer?.Dispose(); observer = null;
        outbox?.Dispose(); outbox = null;
        owns = false; Interlocked.Exchange(ref active, 0);
    }
    protected override void OnRemove() => OnStop();
}
