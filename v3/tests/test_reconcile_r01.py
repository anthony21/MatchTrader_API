import importlib.util
from pathlib import Path

import pytest


def module():
    spec = importlib.util.spec_from_file_location(
        "reconcile_r01", Path(__file__).parents[1] / "scripts/reconcile_r01.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def event(line, kind="intent", label="R01_sample", sl="98.005", tp="104.005"):
    return {
        "source_line": line,
        "kind": kind,
        "label": label,
        "symbol": "XAUUSD",
        "side": "long",
        "entry": "100",
        "sl": sl,
        "tp": tp,
        "utc": f"2026-09-08T12:00:{line:02d}Z",
        "time": module().utc(f"2026-09-08T12:00:{line:02d}Z"),
    }


def trade():
    return {"Side": "BUY", "Symbol": "XAUUSD", "Open Price": "99.99", "Stop Loss": "98", "Take Profit": "104"}


def test_regrades_preserve_old_brackets_and_origin_intent():
    m = module()
    states, _ = m.states_from_events([event(1), event(2, "regrade", sl="99", tp="102")])
    result = m.candidates(trade(), states)
    assert len(result) == 1
    assert result[0]["first"]["source_line"] == 1
    assert result[0]["episode"]["intent"]["source_line"] == 1


def test_reused_label_is_ambiguous_instead_of_nearest_time_assignment():
    m = module()
    states, _ = m.states_from_events([event(1), event(2, "cancelled"), event(3)])
    assert len(m.candidates(trade(), states)) == 2


def test_quote_touch_does_not_create_an_additional_order():
    m = module()
    states, _ = m.states_from_events([event(1), event(2, "touched")])
    assert len(m.candidates(trade(), states)) == 1


def test_side_symbol_and_both_brackets_are_required():
    m = module()
    states, _ = m.states_from_events([event(1)])
    for changes in ({"Side": "SELL"}, {"Symbol": "EURUSD"}, {"Take Profit": "105"}, {"Stop Loss": "97"}):
        assert not m.candidates(trade() | changes, states)


def test_footer_is_not_a_winning_trade_and_total_is_checked(tmp_path):
    path = tmp_path / "broker.csv"
    path.write_text("ID,Profit\nW1,10.50\nW2,-2.25\nTOTAL,8.25\n")
    trades, total = module().broker_rows(path)
    assert len(trades) == 2
    assert str(total) == "8.25"
    path.write_text("ID,Profit\nW1,10.50\nTOTAL,11\n")
    with pytest.raises(ValueError, match="reconcile"):
        module().broker_rows(path)


def test_naive_window_and_duplicate_broker_ids_rejected(tmp_path):
    with pytest.raises(ValueError, match="offset"):
        module().utc("2026-09-08T12:00:00")
    path = tmp_path / "broker.csv"
    path.write_text("ID,Profit\nW1,10\nW1,-2\n")
    with pytest.raises(ValueError, match="unique"):
        module().broker_rows(path)


def test_full_report_keeps_missing_send_times_unknown_and_snapshots_sources(tmp_path):
    m = module()
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        "utc,kind,label,symbol,side,entry,sl,tp\n"
        "2026-09-08T12:00:01Z,intent,R01_sample,XAUUSD,long,100,98.005,104.005,extra-field\n"
    )
    broker = tmp_path / "broker.csv"
    broker.write_text(
        "ID,Symbol,Side,Volume,Open Time,Open Price,Stop Loss,Take Profit,Close Time,Close Price,Profit,Reason\n"
        "W1,XAUUSD,BUY,0.1,08/09/2026 12:01:00,99.99,98,104,08/09/2026 12:02:00,104,10,TP\n"
        "TOTAL,,,,,,,,,,10,\n"
    )
    output = tmp_path / "report"
    summary = m.reconcile(
        ledger, broker, output, m.utc("2026-09-08T00:00:00Z"), m.utc("2026-09-09T00:00:00Z"), "TEST_ACCOUNT"
    )
    assert summary["win_percentage"] == 100
    assert summary["confirmed_id_matches"] == 0
    assert summary["matches"] == {"Unique level candidate": 1}
    assert (output / "source-snapshots/ledger.csv").read_bytes() == ledger.read_bytes()
    import csv

    with (output / "side-by-side.csv").open() as stream:
        row = next(csv.DictReader(stream))
    assert row["qt_send_utc"] == row["broker_received_utc"] == ""
    assert row["qt_state_utc"] == "2026-09-08T12:00:01Z"
    assert (output / "side-by-side.html").is_file()
