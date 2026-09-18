namespace HCAMM.QuantowerCapture;

/// <summary>Explicit hook for editable R01/X17 code; signals are observations only.</summary>
public static class CapturePublisher
{
    static Action<CaptureEvent>? sink;
    internal static void Attach(Action<CaptureEvent>? value) => Volatile.Write(ref sink, value);
    public static bool PublishSignal(CaptureEvent signal)
    {
        var current = Volatile.Read(ref sink);
        if (current == null) return false;
        if (signal.Source is not ("R01" or "X17")) throw new ArgumentException("Explicit strategy source required");
        current(signal with { Kind = "SIGNAL", Action = "OBSERVE" });
        return true;
    }
}
