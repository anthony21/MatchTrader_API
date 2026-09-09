from datetime import datetime

import pytest

from matchtrader.bridge import ShadowBridge


def test_account_gate_and_no_broker_timestamps(tmp_path, event_payload):
    with ShadowBridge("456", tmp_path / "journal.db") as bridge:
        result = bridge.receive(event_payload)
        assert result["reason"] == "account_mismatch"
        assert result["broker_request_started_at"] is None
        assert result["broker_order_id"] is None


def test_revisions_and_repeated_create_are_held(tmp_path, event_payload):
    with ShadowBridge("123", tmp_path / "journal.db") as bridge:
        assert bridge.receive(event_payload)["status"] == "preview"
        repeated = {**event_payload, "event_id": "event-2", "revision": 2}
        assert bridge.receive(repeated)["reason"] == "stale_revision_or_repeated_create"
        stale = {**event_payload, "event_id": "event-3", "action": "EDIT"}
        assert bridge.receive(stale)["reason"] == "stale_revision_or_repeated_create"


def test_receipt_requires_timezone(tmp_path, event_payload):
    with ShadowBridge("123", tmp_path / "journal.db") as bridge:
        with pytest.raises(ValueError, match="timezone"):
            bridge.receive(event_payload, received_at=datetime(2026, 9, 9))


def test_no_implicit_account(tmp_path):
    with pytest.raises(ValueError):
        ShadowBridge("", tmp_path / "journal.db")
