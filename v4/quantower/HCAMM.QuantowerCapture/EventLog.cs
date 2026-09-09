using System.Globalization;

namespace HCAMM.QuantowerCapture;

public static class EventLog
{
    static string Clean(string? value) => new((value ?? "").Take(250).Select(c => char.IsControl(c) ? ' ' : c).ToArray());
    public static string Captured(CaptureEvent e) => FormattableString.Invariant(
        $"QT {e.EmittedAt:O} | {Clean(e.Source)} {Clean(e.Kind)}/{Clean(e.Action)} | account {Clean(e.AccountId)} | {Clean(e.Symbol)} {Clean(e.Side)} qty={e.Quantity} entry={e.Price} SL={e.Sl} TP={e.Tp} | order={Clean(e.OrderId)} label={Clean(e.SourceLabel)} request={Clean(e.RequestId)}");
    public static string Result(CaptureEvent e, string status, string reason, string brokerId) =>
        $"AQUA {DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture)} | {Clean(status)} | QT order={Clean(e.OrderId)} request={Clean(e.RequestId)} | broker={Clean(brokerId)} | {Clean(reason)}";
}
