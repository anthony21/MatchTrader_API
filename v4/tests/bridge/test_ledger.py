import json

import pytest

from matchtrader.bridge.journal import Journal
from matchtrader.bridge.ledger import LedgerTail, observe

HEADER = "utc,kind,label,symbol,side,entry,sl,tp\n"
ROW = "2026-09-09T10:00:00Z,touched,label,XAUUSD,short,2400,2410,2380,extra\n"


def test_starts_at_eof_and_waits_for_complete_line(tmp_path):
    path = tmp_path / "ledger.csv"
    path.write_text(HEADER + ROW)
    tail = LedgerTail(path)
    try:
        assert tail.poll() == []
        with path.open("ab") as stream:
            stream.write(ROW[:-1].encode())
        assert tail.poll() == []
        with path.open("ab") as stream:
            stream.write(b"\n")
        rows = tail.poll()
        assert len(rows) == 1
        assert rows[0][1]["record"]["kind"] == "touched"
        assert rows[0][1]["extra_fields"] == ["extra"]
        assert rows[0][1]["execution_status"] == "not_submitted"
        assert tail.poll() == []
    finally:
        tail.close()


def test_partial_row_present_at_start_is_skipped(tmp_path):
    path = tmp_path / "ledger.csv"
    path.write_text(HEADER + ROW[:20])
    tail = LedgerTail(path)
    try:
        with path.open("ab") as stream:
            stream.write(ROW[20:].encode() + ROW.encode())
        assert len(tail.poll()) == 1
    finally:
        tail.close()


def test_truncation_stops_observation(tmp_path):
    path = tmp_path / "ledger.csv"
    path.write_text(HEADER + ROW)
    tail = LedgerTail(path)
    try:
        path.write_text(HEADER)
        with pytest.raises(RuntimeError, match="truncated"):
            tail.poll()
    finally:
        tail.close()


def test_bounded_observe_journals_new_rows(tmp_path, monkeypatch):
    path = tmp_path / "ledger.csv"
    path.write_text(HEADER)
    clock = iter([0, 0, 1])
    monkeypatch.setattr("matchtrader.bridge.ledger.time.monotonic", lambda: next(clock))

    def append(_):
        with path.open("a") as stream:
            stream.write(ROW)

    monkeypatch.setattr("matchtrader.bridge.ledger.time.sleep", append)
    journal = Journal(tmp_path / "journal.db")
    try:
        result = observe(path, journal, seconds=1)
        assert result["new_observations"] == 1 and result["broker_orders_sent"] == 0
        stored = json.loads(journal.db.execute("SELECT payload FROM observations").fetchone()[0])
        assert stored["classification"] == "ledger_observation_only"
    finally:
        journal.close()
