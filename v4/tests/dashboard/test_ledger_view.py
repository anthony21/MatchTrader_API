"""Ledger stream sections: journal-only values, paper never verified, digest-stable across builds."""

import json
from datetime import UTC, datetime

from matchtrader.capture import CaptureStore
from matchtrader.capture.event import CaptureEvent
from matchtrader.capture.manual_send import send
from matchtrader.capture.pamm_publisher import PammPublisher
from matchtrader.capture.router import CaptureRouter
from matchtrader.dashboard import ledger_view
from matchtrader.dashboard.copy_controls import CopyControls
from matchtrader.dashboard.server import Handler
from matchtrader.models.position import Position
from tests.capture.test_verified import observation, snapshot

SEEN = "2026-09-10T01:00:00+00:00"


def controls(mode="paper", **sources):
    return CopyControls.model_validate({"mode": mode, "sources": sources})


def candidate(**overrides):
    fields = {"trade_id": "c1", "source": "P01", "state": "observed",
              "links": [{"side": "source", "kind": "order", "native_id": "o1"}],
              "actions": [], "outcome_reasons": []}
    fields.update(overrides)
    return snapshot(**fields)


def verified(**overrides):
    fields = {
        "trade_id": "v1", "source": "X17", "lots": "0.02",
        "destination_observations": [observation(open_time_millis=1789000000000, first_seen_at=SEEN,
                                                 volume="0.02", open_price="1.15")],
        "actions": [{"action_key": "CREATE", "updated_at": "2026-09-10T00:59:00+00:00"}],
    }
    fields.update(overrides)
    return snapshot(**fields)


def signal(event_id, order_id, source="MANUAL"):
    return CaptureEvent(
        event_id=event_id, machine="qt", connection_id="connection", account_id="source", order_id=order_id,
        request_id="run:" + order_id, emitted_at=datetime.now(UTC), kind="ACCEPTED", action="CREATE",
        source=source, symbol="EURUSD", side="BUY", order_type="LIMIT", quantity="1", price="1.15000",
        sl="1.14980", tp="1.16",
    )


def test_candidate_row_is_unverified_and_reports_source_eligibility():
    row = ledger_view.verified_row(candidate(), controls(P01=True), None)
    assert row["state"] == "candidate" and row["verified"] is False and row["source_enabled"] is True
    assert row["source"] == {"code": "P01", "scope": None, "order_ids": ["o1"], "position_ids": []}
    assert row["destination"] == {"broker": "", "account_id": "demo", "order_ids": [], "position_ids": []}
    assert row["timestamps"] == {"sent_at": None, "confirmed_at": None, "broker_open": None,
                                 "broker_open_millis": None}
    assert row["read_back"] is None and row["pamm"] is None and row["cancellation"] is None
    assert row["reasons"][0].startswith("No destination position identity")
    assert ledger_view.verified_row(candidate(), controls(X17=True), None)["source_enabled"] is False


def test_paper_sent_row_is_never_verified_and_says_so_first():
    row = ledger_view.verified_row(candidate(), controls(P01=True), None, paper_sent=True)
    assert row["state"] == "paper_sent" and row["verified"] is False
    assert row["reasons"][0].startswith("Sent in paper mode")
    assert row["destination"]["position_ids"] == [] and row["read_back"] is None and row["pamm"] is None


def test_verified_row_carries_read_back_evidence_timestamps_and_publication():
    publication = {"trade_id": "v1", "published_at": "2026-09-10T01:01:00+00:00", "upstream_status": 200}
    row = ledger_view.verified_row(verified(), controls(), publication)
    assert row["state"] == "verified_open" and row["verified"] is True and row["lots"] == "0.02"
    assert row["timestamps"] == {"sent_at": "2026-09-10T00:59:00+00:00", "confirmed_at": SEEN,
                                 "broker_open": None, "broker_open_millis": 1789000000000}
    assert row["read_back"] == {"reader": "open_positions", "volume": "0.02", "open_price": "1.15"}
    assert row["pamm"] == {"published": True, "published_at": "2026-09-10T01:01:00+00:00",
                           "upstream_status": 200}
    assert row["destination"]["position_ids"] == ["p1"] and row["source_enabled"] is False
    failed = ledger_view.verified_row(verified(), controls(), {**publication, "upstream_status": None})
    assert failed["pamm"]["published"] is False and failed["state"] == "verified_open"


def test_cancellation_prefers_the_recorded_reason_then_a_source_ending_before_any_send():
    reason = {"origin": "broker", "outcome": "uncertain", "code": "APIError", "summary": "s", "evidence": "e",
              "at": "2026-09-10T00:00:00+00:00", "attempt": 1}
    row = ledger_view.verified_row(candidate(outcome_reasons=[{**reason, "code": "older"}, reason]),
                                   controls(), None)
    assert row["cancellation"] == {k: reason[k] for k in ("origin", "outcome", "code", "summary", "evidence", "at")}
    ended = ledger_view.verified_row(candidate(source_state="Cancelled", updated_at="t"), controls(), None)
    assert ended["cancellation"]["origin"] == "source" and ended["cancellation"]["code"] == "Cancelled"
    assert ended["cancellation"]["at"] == "t"
    # A source that ended after the destination was filled is not "cancelled before any send".
    assert ledger_view.verified_row(verified(source_state="Removed"), controls(), None)["cancellation"] is None
    assert ledger_view.verified_row(candidate(source_state="Filled"), controls(), None)["cancellation"] is None


def test_paper_sends_and_paper_ids_come_from_the_journal_scoped_to_the_account(tmp_path):
    store = CaptureStore(tmp_path)
    router = CaptureRouter(store)
    first = router.receive(signal("e1", "o1").model_dump())["trade_id"]
    second = router.receive(signal("e2", "o2").model_dump())["trade_id"]
    result = send(store, controls(MANUAL=True), first, "0.25", None, "demo")
    assert ledger_view.paper_sent_ids(store, []) == set() and ledger_view.paper_sent_ids(store, [""]) == set()
    assert ledger_view.paper_sent_ids(store, [first, second, first]) == {first}
    view = ledger_view.paper_sends(store, "demo")
    assert view["account_id"] == "demo" and len(view["rows"]) == 1
    (row,) = view["rows"]
    assert row["trade_id"] == first and row["source"] == "MANUAL" and row["symbol"] == "EURUSD"
    assert row["side"] == "BUY" and row["lots"] == "0.25" and row["request"] == result["request"]
    assert row["verdict"] == "would_send" and row["decided_at"] == result["decided_at"] and row["reason"]
    assert ledger_view.paper_sends(store, "other")["rows"] == []
    ledger = ledger_view.verified_trades(store.mapping_view("demo"), controls(MANUAL=True), {}, {first}, "demo")
    states = {r["trade_id"]: r["state"] for r in ledger["rows"]}
    assert states == {first: "paper_sent", second: "candidate"}
    assert not any(r["verified"] for r in ledger["rows"])
    store.close()


def test_sections_hash_identically_across_two_builds_with_no_new_evidence(tmp_path):
    store = CaptureStore(tmp_path)
    router = CaptureRouter(store)
    paper = router.receive(signal("e1", "o1").model_dump())["trade_id"]
    router.receive(signal("e2", "o2", "P01").model_dump())
    live = router.receive(signal("e3", "o3", "X17").model_dump())["trade_id"]
    send(store, controls(MANUAL=True), paper, "0.25", None, "demo")
    store.update(live, destination="demo", broker_position_id="p1", state="open", lots="0.02")
    store.observe_positions(live, "demo", [Position(id="p1", symbol="EURUSD", side="BUY", volume="0.02",
                                                   openPrice="1.15", openTimeMillis=1789000000000)])
    forwarder = type("Forwarder", (), {
        "url": "https://tradingbox.pro/api/hcamm/events", "api_key": "k", "auth_header": "X-HCAMM-Key",
        "ticket": lambda self: (1, True, True), "send": lambda self, *a, **k: (200, "OK", [], b"{}"),
    })()
    pamm = PammPublisher(store, lambda: forwarder)
    assert len(pamm.sweep(store.mapping_view("demo"))) == 1
    active = controls("live", MANUAL=True, X17=True)

    def build():
        snapshots = store.mapping_view("demo")
        ids = [s["trade_id"] for s in snapshots]
        return {
            "verified_trades": ledger_view.verified_trades(snapshots, active, pamm.publications(ids),
                                                           ledger_view.paper_sent_ids(store, ids), "demo"),
            "paper_sends": ledger_view.paper_sends(store, "demo"),
            "copy_controls": active.model_dump(mode="json"),
        }

    first, second = build(), build()
    states = {r["trade_id"]: (r["state"], r["verified"]) for r in first["verified_trades"]["rows"]}
    assert states[paper] == ("paper_sent", False) and states[live] == ("verified_open", True)
    published = next(r for r in first["verified_trades"]["rows"] if r["trade_id"] == live)
    assert published["pamm"]["published"] is True
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(second, sort_keys=True, default=str)
    for name in first:
        assert Handler.section_digest(name, first[name]) == Handler.section_digest(name, second[name]), name
    store.close()
