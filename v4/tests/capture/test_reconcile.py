from decimal import Decimal
from types import SimpleNamespace

from matchtrader.capture import CaptureStore
from matchtrader.capture.reconcile import reconcile
from matchtrader.capture.verified import NO_READ_CLOSURE_REASON, classify
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


def test_closed_history_records_destination_evidence_even_on_partial_close(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    store.update(
        identity,
        destination='demo',
        broker_order_id='o1',
        broker_position_id='p1',
        symbol='EURUSD',
        side='BUY',
        lots='.02',
        state='open',
    )
    closed = SimpleNamespace(id='p1', symbol='EURUSD', side='BUY', volume=Decimal('.01'),
                             openTime='2024-01-01T00:00:00Z', time='2024-01-02T00:00:00Z',
                             closeReason='CLIENT')
    api = SimpleNamespace(active_orders=lambda: [], closed_positions=lambda **kwargs: [closed])
    reconcile(store, api, 'demo', [])
    observed = store.mapping_view('demo')[0]['destination_observations'][0]
    assert observed['open_time'] == '2024-01-01T00:00:00Z'
    assert observed['close_reason'] == 'CLIENT'
    # A partial close alone must not resolve the trade.
    assert store.trade(identity)['state'] == 'open'
    store.close()


def test_partial_close_is_verified_but_not_reported_closed(tmp_path, event):
    # This was the P2 bug: a closed-reader row with timed evidence was classified
    # verified_closed even though reconcile() correctly left the trade open because the
    # matched volume did not cover the trade's lots. Broker execution IS verified here;
    # the position is simply not yet fully closed, so it must classify as verified_open.
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    store.update(
        identity,
        destination='demo',
        broker_order_id='o1',
        broker_position_id='p1',
        symbol='EURUSD',
        side='BUY',
        lots='.02',
        state='open',
    )
    closed = SimpleNamespace(id='p1', symbol='EURUSD', side='BUY', volume=Decimal('.01'),
                             openTime='2024-01-01T00:00:00Z', time='2024-01-02T00:00:00Z',
                             closeReason='CLIENT')
    api = SimpleNamespace(active_orders=lambda: [], closed_positions=lambda **kwargs: [closed])
    reconcile(store, api, 'demo', [])
    assert store.trade(identity)['state'] == 'open'
    classification = classify(store.mapping_view('demo')[0])
    assert classification['verified']
    assert classification['state'] == 'verified_open'
    assert NO_READ_CLOSURE_REASON in classification['reasons']
    store.close()


def test_two_partial_closes_via_reconcile_sum_to_a_verified_closed_trade(tmp_path, event):
    # Regression for defect B's schema fix: distinct closing executions (distinguished by uid)
    # against the same position must be retained as separate destination_observations rows so
    # their volumes can be summed to reach the trade's full requested quantity.
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    store.update(
        identity,
        destination='demo',
        broker_order_id='o1',
        broker_position_id='p1',
        symbol='EURUSD',
        side='BUY',
        lots='.02',
        state='open',
    )
    first = SimpleNamespace(id='p1', uid='close-1', symbol='EURUSD', side='BUY', volume=Decimal('.01'),
                            openTime='2024-01-01T00:00:00Z', time='2024-01-02T00:00:00Z',
                            closeReason='CLIENT')
    second = SimpleNamespace(id='p1', uid='close-2', symbol='EURUSD', side='BUY', volume=Decimal('.01'),
                             openTime='2024-01-01T00:00:00Z', time='2024-01-03T00:00:00Z',
                             closeReason='CLIENT')
    api = SimpleNamespace(active_orders=lambda: [], closed_positions=lambda **kwargs: [first, second])
    reconcile(store, api, 'demo', [])
    assert store.trade(identity)['state'] == 'resolved'
    observations = store.mapping_view('demo')[0]['destination_observations']
    assert len({o['execution_key'] for o in observations if o['reader'] == 'closed_positions'}) == 2
    classification = classify(store.mapping_view('demo')[0])
    assert classification['verified']
    assert classification['state'] == 'verified_closed'
    store.close()


def test_full_close_is_verified_closed(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    store.update(
        identity,
        destination='demo',
        broker_order_id='o1',
        broker_position_id='p1',
        symbol='EURUSD',
        side='BUY',
        lots='.02',
        state='open',
    )
    closed = SimpleNamespace(id='p1', symbol='EURUSD', side='BUY', volume=Decimal('.02'),
                             openTime='2024-01-01T00:00:00Z', time='2024-01-02T00:00:00Z',
                             closeReason='CLIENT')
    api = SimpleNamespace(active_orders=lambda: [], closed_positions=lambda **kwargs: [closed])
    reconcile(store, api, 'demo', [])
    assert store.trade(identity)['state'] == 'resolved'
    classification = classify(store.mapping_view('demo')[0])
    assert classification['verified']
    assert classification['state'] == 'verified_closed'
    store.close()
