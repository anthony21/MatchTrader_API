using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Utils;
using System.Text.Json;

namespace HCAMM.QuantowerCapture;

public sealed class NativeObserver(CaptureConfig config, Action<CaptureEvent> send, Action? fault = null) : IDisposable
{
    readonly string run = Guid.NewGuid().ToString("N");
    readonly HashSet<Order> orders = new();
    readonly HashSet<Position> positions = new();
    readonly object gate = new();
    readonly Dictionary<string, string> lastState = new();

    void Safe(Action callback) { try { callback(); } catch { fault?.Invoke(); } }
    void Changed(CaptureEvent item)
    {
        var key = string.Join("|", item.ConnectionId, item.AccountId, item.Kind, item.OrderId, item.PositionId);
        var state = JsonSerializer.Serialize(item with { EventId = "", EmittedAt = DateTimeOffset.UnixEpoch }, CaptureEvent.Json);
        lock (gate) { if (lastState.TryGetValue(key, out var previous) && previous == state) return; if (lastState.Count >= 10000) lastState.Clear(); lastState[key] = state; }
        send(item);
    }

    public void Start()
    {
        Core.Instance.NewRequest += Request;
        Core.Instance.NewPerformedRequest += Performed;
        Core.Instance.OrderAdded += Added;
        Core.Instance.OrderRemoved += Removed;
        Core.Instance.PositionAdded += PositionAdded;
        Core.Instance.PositionRemoved += PositionRemoved;
        Core.Instance.TradeAdded += Trade;
        foreach (var account in Core.Instance.Accounts)
            send(new CaptureEvent { Kind = "ACCOUNT", AccountId = account.Id, ConnectionId = account.ConnectionId,
                Status = account.Name, Snapshot = true });
        foreach (var order in Core.Instance.Orders) { Watch(order); send(OrderEvent(order) with { Snapshot = true }); }
        foreach (var position in Core.Instance.Positions) { Watch(position); send(PositionEvent(position) with { Snapshot = true }); }
    }
    static decimal Number(double value) => double.IsFinite(value) && value > 0 ? (decimal)value : 0;
    public static string OrderKind(OrderTypeBehavior behavior) => behavior switch
    { OrderTypeBehavior.Market => "MARKET", OrderTypeBehavior.Limit => "LIMIT", OrderTypeBehavior.Stop => "STOP", OrderTypeBehavior.StopLimit => "STOP_LIMIT", _ => "UNKNOWN" };
    static string SideName(Side side) => side == Side.Buy ? "BUY" : "SELL";
    static CaptureEvent Basis(Account account, Symbol symbol, Side side) => new()
    { ConnectionId = account.ConnectionId, AccountId = account.Id, Symbol = symbol.Name, Side = SideName(side) };
    static bool Absolute(SlTpHolder? value) => value == null || value.Price == 0 || value.PriceMeasurement == PriceMeasurement.Absolute;

    static CaptureEvent OrderEvent(IOrder order) => Basis(order.Account, order.Symbol, order.Side) with
    {
        OrderId = order.Id, PositionId = order.PositionId ?? "", Kind = "ORDER", Status = order.Status.ToString(),
        OrderType = OrderKind(order.OrderType?.Behavior ?? OrderTypeBehavior.Unspecified), Quantity = Number(order.TotalQuantity),
        Price = Number(order.OrderType?.Behavior == OrderTypeBehavior.Stop ? order.TriggerPrice : order.Price),
        Sl = Number(order.StopLoss?.Price ?? 0), Tp = Number(order.TakeProfit?.Price ?? 0),
        BracketsAbsolute = Absolute(order.StopLoss) && Absolute(order.TakeProfit)
    };
    static CaptureEvent PositionEvent(Position p) => Basis(p.Account, p.Symbol, p.Side) with
    { Kind = "POSITION", PositionId = p.Id, OrderType = "MARKET", Quantity = Number(p.Quantity), Price = Number(p.OpenPrice), Sl = Number(p.StopLoss?.TriggerPrice ?? 0), Tp = Number(p.TakeProfit?.Price ?? 0) };

    CaptureEvent? FromRequest(RequestParameters request)
    {
        CaptureEvent? item = null;
        if (request is OrderRequestParameters p && p.Account != null && p.Symbol != null)
            item = Basis(p.Account, p.Symbol, p.Side) with
            {
                Action = request is ModifyOrderRequestParameters ? "EDIT" : "CREATE",
                OrderId = (request as ModifyOrderRequestParameters)?.OrderId ?? "", PositionId = p.PositionId ?? "",
                Quantity = Number(p.Quantity), OrderType = OrderKind(p.OrderType?.Behavior ?? OrderTypeBehavior.Unspecified),
                Price = Number(p.OrderType?.Behavior == OrderTypeBehavior.Stop ? p.TriggerPrice : p.Price),
                Sl = Number(p.StopLoss?.Price ?? 0), Tp = Number(p.TakeProfit?.Price ?? 0),
                BracketsAbsolute = Absolute(p.StopLoss) && Absolute(p.TakeProfit)
            };
        else if (request is CancelOrderRequestParameters cancel && cancel.Order != null)
            item = OrderEvent(cancel.Order) with { Action = "CANCEL" };
        else if (request is ClosePositionRequestParameters close && close.Position != null)
            item = PositionEvent(close.Position) with { Action = "CLOSE", Quantity = Number(close.CloseQuantity) };
        return item == null ? null : item with { RequestId = run + ":" + request.RequestId, SendingSource = request.SendingSource ?? "", Source = config.Source(request.SendingSource) };
    }
    void Request(object? sender, RequestEventArgs e)
    { Safe(() => { var item = FromRequest(e.RequestParameters); if (item != null) send(item with { Kind = "REQUEST" }); }); }
    void Performed(object? sender, PerformedRequestEventArgs e)
    {
        Safe(() => {
        var item = FromRequest(e.RequestParameters);
        if (item == null || e.RequestResult is not TradingOperationResult result) return;
        send(item with { Kind = result.Status == TradingOperationResultStatus.Success ? "ACCEPTED" : "REJECTED",
                         OrderId = item.OrderId.Length > 0 ? item.OrderId : result.OrderId ?? "", Status = result.Status.ToString() });
        });
    }
    void Watch(Order o) { lock (gate) if (orders.Add(o)) o.Updated += Updated; }
    void Watch(Position p) { lock (gate) if (positions.Add(p)) p.Updated += PositionUpdated; }
    void Added(Order o) => Safe(() => { Watch(o); Changed(OrderEvent(o)); });
    void Removed(Order o) => Safe(() => { lock (gate) { if (orders.Remove(o)) o.Updated -= Updated; } Changed(OrderEvent(o)); });
    void Updated(IOrder o) => Safe(() => Changed(OrderEvent(o)));
    void PositionAdded(Position p) => Safe(() => { Watch(p); Changed(PositionEvent(p)); });
    void PositionUpdated(Position p) => Safe(() => Changed(PositionEvent(p)));
    void PositionRemoved(Position p) => Safe(() => { lock (gate) { if (positions.Remove(p)) p.Updated -= PositionUpdated; } Changed(PositionEvent(p) with { Status = "Removed" }); });
    void Trade(Trade t) => Safe(() => send(Basis(t.Account, t.Symbol, t.Side) with { Kind = "FILL", OrderId = t.OrderId ?? "", PositionId = t.PositionId ?? "", ExecutionId = t.Id, Quantity = Number(t.Quantity), Price = Number(t.Price), Status = "Filled" }));

    public void Dispose()
    {
        Core.Instance.NewRequest -= Request; Core.Instance.NewPerformedRequest -= Performed;
        Core.Instance.OrderAdded -= Added; Core.Instance.OrderRemoved -= Removed;
        Core.Instance.PositionAdded -= PositionAdded; Core.Instance.PositionRemoved -= PositionRemoved; Core.Instance.TradeAdded -= Trade;
        lock (gate) { foreach (var o in orders) o.Updated -= Updated; foreach (var p in positions) p.Updated -= PositionUpdated; orders.Clear(); positions.Clear(); lastState.Clear(); }
    }
}
