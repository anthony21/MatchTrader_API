import csv
import hashlib
from decimal import Decimal

import pytest

from matchtrader.capture import CaptureStore


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
