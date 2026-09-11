import csv
import hashlib
from decimal import Decimal
from types import SimpleNamespace

import pytest

from matchtrader.capture import CaptureStore
from matchtrader.models.position import Position


def test_v3_event_replay_keeps_identity_after_optional_field_added(tmp_path, event):
    store = CaptureStore(tmp_path)
    first, _ = store.record(event)
    old_payload = event.model_dump_json(exclude={"source_label"})
    with store.db:
        store.db.execute(
            "UPDATE events SET payload=?,digest=? WHERE seq=?",
            (old_payload, hashlib.sha256(old_payload.encode()).hexdigest(), first["seq"]),
        )
    replay, duplicate = store.record(event)
    assert duplicate and replay["trade_id"] == first["trade_id"]
    with pytest.raises(ValueError, match="different"):
        store.record(event.model_copy(update={"source_label": "P01RR_123456_1"}))
    store.close()


def test_id_survives_retention_restarts_and_duplicate_actions(tmp_path, event):
    store = CaptureStore(tmp_path, limit=2)
    first, _ = store.record(event)
    identity = first["trade_id"]
    assert store.claim(identity, "CREATE")
    store.close()
    store = CaptureStore(tmp_path, limit=2)
    assert store.trade(identity)["state"] == "uncertain"
    assert not store.claim(identity, "CREATE")
    for i in range(4):
        store.record(event.model_copy(update={"event_id": f"e{i}", "order_id": f"o{i}"}))
    assert len(list(csv.DictReader(store.csv_path.open(encoding="utf-8-sig")))) == 2
    old, duplicate = store.record(event)
    assert duplicate and old["trade_id"] == identity
    store.close()


def test_id_collision_account_isolation_and_fill_link(tmp_path, event):
    store = CaptureStore(tmp_path)
    first, _ = store.record(event)
    with pytest.raises(ValueError, match="different"):
        store.record(event.model_copy(update={"quantity": Decimal(2)}))
    second, _ = store.record(event.model_copy(update={"event_id": "e2", "account_id": "other"}))
    assert second["trade_id"] != first["trade_id"]
    store.record(event.model_copy(update={"event_id": "fill", "kind": "FILL", "position_id": "p1"}))
    close, _ = store.record(
        event.model_copy(update={"event_id": "close", "order_id": "", "position_id": "p1"})
    )
    assert close["trade_id"] == first["trade_id"]
    store.close()


def test_action_details_survive_crash_without_replay(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    assert store.claim(identity, 'CREATE', event=event, destination='demo', request={'instrument': 'EURUSD'})
    store.close()
    store = CaptureStore(tmp_path)
    snapshot = store.mapping_view('demo')[0]
    assert snapshot['mapping_status'] == 'uncertain'
    assert snapshot['actions'][0]['outcome'] == 'uncertain'
    assert snapshot['actions'][0]['request'] == {'instrument': 'EURUSD'}
    assert not store.claim(identity, 'CREATE', event=event, destination='demo', request={})
    store.close()


def test_feed_preserves_trade_origin_on_manual_update(tmp_path, event):
    store = CaptureStore(tmp_path)
    first, _ = store.record(event.model_copy(update={'source': 'R01'}))
    store.record(event.model_copy(update={'event_id': 'edit', 'source': 'MANUAL', 'action': 'EDIT'}))
    latest = store.feed()[0]
    assert latest['trade_id'] == first['trade_id']
    assert latest['source'] == 'MANUAL'
    assert latest['meaning']['source']['code'] == 'R01'
    assert latest['meaning']['action_source'] == 'MANUAL'
    assert latest['meaning']['opened']['state'] == 'unconfirmed'
    store.close()


def test_stream_wakes_for_commit_and_decision_and_closes_cleanly(tmp_path, event):
    from concurrent.futures import ThreadPoolExecutor

    store = CaptureStore(tmp_path)
    initial = store.stream_snapshot()
    assert initial == {'revision': 0, 'events': []}
    with ThreadPoolExecutor() as executor:
        pending = executor.submit(store.stream_snapshot, 0, 2)
        row, _ = store.record(event)
        received = pending.result(timeout=2)
        assert received['events'][0]['event_id'] == event.event_id
        store.decision(row['seq'], 'held', 'Capture only')
        decision = store.stream_snapshot(received['revision'], timeout=0)
        assert decision['events'][0]['decision'] == 'held'
        assert store.stream_snapshot(decision['revision'], timeout=0) == {'revision': decision['revision']}
        store.record(event)  # Duplicate replay creates no new stream revision.
        assert store.revision == decision['revision']
        pending = executor.submit(store.stream_snapshot, decision['revision'], 2)
        store.close()
        assert pending.result(timeout=2) is None


def test_background_csv_does_not_block_journal_and_flushes_on_close(tmp_path, event, monkeypatch):
    from threading import Event

    store = CaptureStore(tmp_path, background_exports=True)
    entered, release = Event(), Event()
    original = store._export_now
    def slow_export():
        entered.set()
        assert release.wait(3)
        original()
    monkeypatch.setattr(store, '_export_now', slow_export)
    try:
        store.record(event)
        assert entered.wait(2)
        store.record(event.model_copy(update={'event_id': 'next', 'order_id': 'next'}))
        assert len(store.feed()) == 2
    finally:
        release.set()
        store.close()
    assert len(list(csv.DictReader(store.csv_path.open(encoding='utf-8-sig')))) == 2


def test_observe_positions_persists_open_time_fields(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    position = Position(id='p1', symbol='EURUSD', side='BUY', volume='.01', openPrice='1.15',
                        openTime='2024-01-01T00:00:00Z', openTimeMillis=1700000000000)
    store.observe_positions(identity, 'demo', [position])
    scope = store.mappings.destination_scope('demo')
    saved = store.db.execute(
        "SELECT open_time,open_time_millis FROM destination_observations "
        "WHERE trade_id=? AND scope=? AND position_id='p1'", (identity, scope),
    ).fetchone()
    assert saved['open_time'] == '2024-01-01T00:00:00Z'
    assert saved['open_time_millis'] == 1700000000000
    store.close()


def test_observe_positions_leaves_open_time_null_when_absent(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    position = Position(id='p2', symbol='EURUSD', side='BUY', volume='.01', openPrice='1.15')
    store.observe_positions(identity, 'demo', [position])
    scope = store.mappings.destination_scope('demo')
    saved = store.db.execute(
        "SELECT open_time,open_time_millis FROM destination_observations "
        "WHERE trade_id=? AND scope=? AND position_id='p2'", (identity, scope),
    ).fetchone()
    assert saved['open_time'] is None
    assert saved['open_time_millis'] is None
    store.close()


def test_observe_positions_normalizes_blank_open_time_and_keeps_millis(tmp_path, event):
    # Position.openTime can arrive as '' rather than None. COALESCE('', open_time) returns ''
    # and would erase a valid stored timestamp, so it must be normalized to None before SQL.
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    position = Position(id='p3', symbol='EURUSD', side='BUY', volume='.01', openPrice='1.15',
                        openTime='', openTimeMillis=1700000000000)
    store.observe_positions(identity, 'demo', [position])
    scope = store.mappings.destination_scope('demo')
    saved = store.db.execute(
        "SELECT open_time,open_time_millis FROM destination_observations "
        "WHERE trade_id=? AND scope=? AND position_id='p3'", (identity, scope),
    ).fetchone()
    assert saved['open_time'] is None
    assert saved['open_time_millis'] == 1700000000000
    store.close()


def test_observe_positions_normalizes_whitespace_only_open_time_without_millis(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    position = Position(id='p4', symbol='EURUSD', side='BUY', volume='.01', openPrice='1.15', openTime='   ')
    store.observe_positions(identity, 'demo', [position])
    scope = store.mappings.destination_scope('demo')
    saved = store.db.execute(
        "SELECT open_time,open_time_millis FROM destination_observations "
        "WHERE trade_id=? AND scope=? AND position_id='p4'", (identity, scope),
    ).fetchone()
    assert saved['open_time'] is None
    assert saved['open_time_millis'] is None
    store.close()


def test_observe_closed_normalizes_blank_open_time(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    closed = SimpleNamespace(id='p5', symbol='EURUSD', side='BUY', volume=Decimal('.01'), openTime='',
                             time='2024-01-02T00:00:00Z', closeReason='CLIENT')
    store.observe_closed(identity, 'demo', [closed])
    scope = store.mappings.destination_scope('demo')
    saved = store.db.execute(
        "SELECT open_time,open_time_millis FROM destination_observations "
        "WHERE trade_id=? AND scope=? AND position_id='p5'", (identity, scope),
    ).fetchone()
    assert saved['open_time'] is None
    assert saved['open_time_millis'] is None
    store.close()


def test_observe_closed_retains_every_partial_close_without_broker_execution_ids(tmp_path, event):
    # uid and closingOrderID are both optional on ClosedTrade. Falling back to the position id
    # alone collapsed every partial close onto one row and lost the earlier broker evidence.
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    closes = [
        SimpleNamespace(id='p6', symbol='EURUSD', side='BUY', volume=Decimal('.4'),
                        openTime='2024-01-01T00:00:00Z', time='2024-01-02T00:00:00Z', closeReason='CLIENT'),
        SimpleNamespace(id='p6', symbol='EURUSD', side='BUY', volume=Decimal('.6'),
                        openTime='2024-01-01T00:00:00Z', time='2024-01-03T00:00:00Z', closeReason='CLIENT'),
    ]
    store.observe_closed(identity, 'demo', closes)
    scope = store.mappings.destination_scope('demo')
    saved = store.db.execute(
        "SELECT volume FROM destination_observations WHERE trade_id=? AND scope=? "
        "AND position_id='p6' AND reader='closed_positions'", (identity, scope),
    ).fetchall()
    assert len(saved) == 2
    assert sum(Decimal(r['volume']) for r in saved) == Decimal('1.0')
    store.close()


def test_observe_closed_does_not_double_count_one_close_respelled(tmp_path, event):
    # The broker may spell the same volume '0.5' on one read and '0.50' on the next. Keying the
    # execution on the raw spelling counted one close twice and claimed a complete closure.
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    for volume in ('0.5', '0.50'):
        closed = SimpleNamespace(id='p7', symbol='EURUSD', side='BUY', volume=Decimal(volume),
                                 openTime='2024-01-01T00:00:00Z', time='2024-01-02T00:00:00Z',
                                 closeReason='CLIENT')
        store.observe_closed(identity, 'demo', [closed])
    scope = store.mappings.destination_scope('demo')
    saved = store.db.execute(
        "SELECT volume FROM destination_observations WHERE trade_id=? AND scope=? "
        "AND position_id='p7' AND reader='closed_positions'", (identity, scope),
    ).fetchall()
    assert len(saved) == 1
    assert sum(Decimal(r['volume']) for r in saved) == Decimal('0.5')
    store.close()


def test_observe_closed_keeps_different_sized_closes_at_one_timestamp(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    closes = [
        SimpleNamespace(id='p8', symbol='EURUSD', side='BUY', volume=Decimal('.3'),
                        openTime='2024-01-01T00:00:00Z', time='2024-01-02T00:00:00Z', closeReason='CLIENT'),
        SimpleNamespace(id='p8', symbol='EURUSD', side='BUY', volume=Decimal('.7'),
                        openTime='2024-01-01T00:00:00Z', time='2024-01-02T00:00:00Z', closeReason='CLIENT'),
    ]
    store.observe_closed(identity, 'demo', closes)
    scope = store.mappings.destination_scope('demo')
    saved = store.db.execute(
        "SELECT volume FROM destination_observations WHERE trade_id=? AND scope=? "
        "AND position_id='p8' AND reader='closed_positions'", (identity, scope),
    ).fetchall()
    assert len(saved) == 2
    assert sum(Decimal(r['volume']) for r in saved) == Decimal('1.0')
    store.close()
