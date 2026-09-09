from decimal import Decimal
from types import SimpleNamespace

from matchtrader.capture import CaptureStore
from matchtrader.capture.reconcile import reconcile


def test_only_exact_complete_closed_identity_resolves(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row["trade_id"]
    store.update(
        identity,
        destination="demo",
        broker_order_id="o1",
        broker_position_id="p1",
        symbol="EURUSD",
        side="BUY",
        lots=".02",
        state="open",
    )
    closed = SimpleNamespace(id="p1", symbol="EURUSD", side="BUY", volume=Decimal(".01"))
    api = SimpleNamespace(active_orders=lambda: [], closed_positions=lambda **kwargs: [closed])
    reconcile(store, api, "demo", [])
    assert store.trade(identity)["state"] == "open"
    closed.volume = Decimal(".02")
    closed.id = "different"
    reconcile(store, api, "demo", [])
    assert store.trade(identity)["state"] == "open"
    closed.id = "p1"
    reconcile(store, api, "demo", [])
    assert store.trade(identity)["state"] == "resolved"
    store.close()
