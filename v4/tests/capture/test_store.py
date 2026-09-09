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
