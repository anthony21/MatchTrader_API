from concurrent.futures import ThreadPoolExecutor

from matchtrader.bridge.event import OrderEvent
from matchtrader.bridge.journal import Journal


def test_duplicate_persisted_across_restart_and_conflict(tmp_path, event_payload):
    path = tmp_path / "journal.db"
    event = OrderEvent(**event_payload)
    journal = Journal(path)
    journal.record(event, "received", lambda: {"status": "preview"})
    journal.close()
    journal = Journal(path)
    try:
        assert journal.record(event, "later", lambda: None)["duplicate"]
        changed = OrderEvent(**{**event_payload, "volume_lots": "0.03"})
        assert journal.record(changed, "later", lambda: None)["reason"] == "event_id_payload_conflict"
        assert journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    finally:
        journal.close()


def test_concurrent_duplicates_are_one_capture(tmp_path, event_payload):
    journal = Journal(tmp_path / "journal.db")
    event = OrderEvent(**event_payload)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(lambda _: journal.record(event, "now", lambda: {"status": "preview"}), range(8))
            )
        assert sum(bool(result.get("duplicate")) for result in results) == 7
    finally:
        journal.close()


def test_observation_keeps_provenance(tmp_path):
    journal = Journal(tmp_path / "journal.db")
    try:
        journal.observe("now", "ledger.csv", 42, {"kind": "touched"})
        assert journal.db.execute("SELECT source_path,byte_offset FROM observations").fetchone() == (
            "ledger.csv",
            42,
        )
    finally:
        journal.close()
