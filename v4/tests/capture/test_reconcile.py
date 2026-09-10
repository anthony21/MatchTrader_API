from decimal import Decimal
from types import SimpleNamespace

from matchtrader.capture import CaptureStore
from matchtrader.capture.reconcile import reconcile
from matchtrader.models.position import Position


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


def test_split_broker_positions_are_retained_and_aggregate_history_cannot_resolve_merge(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    store.update(identity, destination='demo', broker_order_id='o1', symbol='EURUSD', side='BUY',
                 lots='.02', state='pending')
    positions = [Position(id=f'p{i}', symbol='EURUSD', side='BUY', volume='.01', openPrice='1.15',
                          orderId='o1') for i in (1, 2)]
    api = SimpleNamespace(active_orders=lambda: [], closed_positions=lambda **kwargs: [])
    reconcile(store, api, 'demo', positions)
    assert set(store.mappings.ids(identity, 'destination', 'position')) == {'p1', 'p2'}
    assert store.mapping_view('demo')[0]['mapping_status'] == 'incomplete'
    store.close()
