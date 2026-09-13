from decimal import Decimal

import pytest

from matchtrader.orders.paper_stop_limit import PaperBook, PaperStore, size_lots


def row(kind, label, side, entry, sl, tp, detail="resting limit at range edge", grade="PRIME", symbol="BTCUSD"):
    return {"utc": "2026-09-13T20:00:00.0000000Z", "kind": kind, "label": label, "symbol": symbol, "side": side,
            "entry": entry, "sl": sl, "tp": tp, "grade": grade, "stamp": "88.5", "detail": detail}


def book(**overrides):
    fields = {"symbol": "BTCUSD", "risk": 5, "tolerance": 5, "arm_ttl": 900, "touch_ttl": 45}
    return PaperBook(**{**fields, **overrides})


def kinds(events):
    return [k for k, _ in events]


def test_five_dollar_risk_sizes_to_the_stop_distance_floored_to_the_step():
    assert size_lots(5, "77100", "77060") == Decimal("0.12")      # 5 / 40 = 0.125 -> 0.12
    assert size_lots(5, "77100", "77099.5") == Decimal("10.00")   # 5 / 0.5
    assert size_lots(5, "77100", "76000") == Decimal("0.01")      # below the minimum -> minimum
    with pytest.raises(ValueError):
        size_lots(5, "77100", "77100")


def test_range_edge_intent_arms_a_limit_and_fills_at_the_level_when_the_quote_reaches_it():
    b = book()
    events = b.apply_row(row("intent", "R01_BTCUSD_short_0_1_0_2", "short", "77200", "77240", "77120"), 10, "t0")
    assert kinds(events) == ["armed"]
    plan = events[0][1]
    assert (plan.kind, plan.side, plan.lots) == ("LIMIT", "SELL", Decimal("0.12"))
    assert b.on_quote("77190", "77191", "t1", 1.0) == []              # bid below the sell level: wait
    events = b.on_quote("77200.5", "77201.5", "t2", 2.0)
    assert kinds(events) == ["filled"]
    assert plan.fill_price == Decimal("77200") and plan.fill_bid == Decimal("77200.5")
    assert b.on_quote("77230", "77231", "t3", 3.0) == []              # inside the brackets: stays open
    events = b.on_quote("77239", "77240", "t4", 4.0)                   # ask reaches the SELL stop
    assert kinds(events) == ["closed"]
    assert plan.exit_reason == "SL" and plan.pnl == Decimal("-4.80")   # 40 points * 0.12 lots


def test_beyond_edge_intent_becomes_a_stop_limit_that_never_chases_past_the_tolerance():
    b = book(tolerance=5)
    (kind, plan), = b.apply_row(row("intent", "R01_BTCUSD_B_long_0_9~0_2", "long", "77300", "77280", "77340",
                                    detail="resting stop at beyond edge"), 11, "t0")
    assert kind == "armed" and plan.kind == "STOP_LIMIT" and plan.limit == Decimal("77305")
    assert b.on_quote("77290", "77291", "t1", 1.0) == []              # ask below the trigger
    events = b.on_quote("77309", "77310", "t2", 2.0)                   # gapped past the limit: rest a LIMIT
    assert kinds(events) == ["working"] and plan.triggered_at == "t2"
    events = b.on_quote("77304", "77305", "t3", 3.0)                   # comes back to the limit: fill there
    assert kinds(events) == ["filled"] and plan.fill_price == Decimal("77305")


def test_triggered_stop_limit_inside_the_tolerance_fills_at_market():
    b = book(tolerance=5)
    (_, plan), = b.apply_row(row("intent", "L", "long", "77300", "77280", "77340",
                                 detail="resting stop at beyond edge"), 1, "t0")
    events = b.on_quote("77301", "77302", "t1", 1.0)
    assert kinds(events) == ["filled"] and plan.fill_price == Decimal("77302")


def test_the_book_cancels_by_itself_on_arm_timeout_touch_ttl_and_downgrade():
    b = book(arm_ttl=100, touch_ttl=45, grades=["PRIME", "STRONG"])
    b.apply_row(row("intent", "A", "short", "77200", "77240", "77120"), 1, "t0")
    b.on_quote("77100", "77101", "t1", 0.0)
    (state, plan), = b.on_quote("77100", "77101", "t2", 101.0)
    assert state == "expired" and "not reached within 100" in plan.reason

    b.apply_row(row("intent", "B", "long", "77300", "77280", "77340", detail="resting stop at beyond edge"), 2, "t0")
    assert kinds(b.on_quote("77320", "77321", "t3", 200.0)) == ["working"]
    (state, plan), = b.on_quote("77320", "77321", "t4", 246.0)
    assert state == "expired" and "unfilled after 45" in plan.reason

    b.apply_row(row("intent", "C", "short", "77200", "77240", "77120"), 3, "t0")
    (state, plan), = b.apply_row(row("regrade", "C", "short", "77200", "77240", "77120", grade="WEAK"), 4, "t5")
    assert state == "expired" and "downgrade to WEAK" in plan.reason
    assert b.plans == {}


def test_r01_cancel_rows_are_honoured_but_never_close_a_filled_position():
    b = book()
    b.apply_row(row("intent", "A", "short", "77200", "77240", "77120"), 1, "t0")
    (state, plan), = b.apply_row(row("cancelled", "A", "short", "77200", "77240", "77120",
                                     detail="range id no longer live"), 2, "t1")
    assert state == "cancelled" and "R01 cancelled" in plan.reason

    b.apply_row(row("intent", "B", "short", "77200", "77240", "77120"), 3, "t0")
    b.on_quote("77201", "77202", "t1", 1.0)
    assert b.apply_row(row("cancelled", "B", "short", "77200", "77240", "77120"), 4, "t2") == []
    assert b.plans["B"].state == "filled"


def test_duplicate_intents_from_other_instances_are_counted_and_repriced_ones_replace():
    b = book()
    b.apply_row(row("intent", "A", "short", "77200", "77240", "77120"), 1, "t0")
    assert b.apply_row(row("intent", "A", "short", "77200", "77240", "77120"), 2, "t1") == []
    assert b.plans["A"].duplicates == 1
    events = b.apply_row(row("intent", "A", "short", "77210", "77250", "77130"), 3, "t2")
    assert kinds(events) == ["armed"] and b.plans["A"].entry == Decimal("77210")
    assert [p.state for p in b.done] == ["cancelled"]


def test_wrong_side_brackets_unknown_details_other_symbols_and_rejected_grades_never_arm():
    b = book(grades=["PRIME"])
    held = b.apply_row(row("intent", "A", "short", "76791.46", "76881.93", "76792.11"), 1, "t0")
    assert kinds(held) == ["held"] and "brackets" in held[0][1].reason
    assert kinds(b.apply_row(row("intent", "B", "short", "77200", "77240", "77120", detail="?"), 2, "t0")) == ["ignored"]
    assert b.apply_row(row("intent", "C", "short", "77200", "77240", "77120", symbol="XAUUSD"), 3, "t0") == []
    assert kinds(b.apply_row(row("intent", "D", "short", "77200", "77240", "77120", grade="WEAK"), 4, "t0")) == ["ignored"]
    assert b.plans == {}


def test_store_round_trips_plans_and_reports_them(tmp_path):
    b = book()
    store = PaperStore(tmp_path / "paper.sqlite3")
    (kind, plan), = b.apply_row(row("intent", "A", "short", "77200", "77240", "77120"), 1, "t0")
    store.event("t0", kind, plan)
    (kind, plan), = b.on_quote("77201", "77202", "t1", 1.0)
    store.event("t1", kind, plan)
    rows, quotes = store.report()
    assert len(rows) == 1 and rows[0]["state"] == "filled" and rows[0]["fill_price"] == "77200"
    assert quotes[0] == 0
