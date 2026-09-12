"""PAMM publication: Aqua, then verify, then publish - never before, never twice, never a retry."""

import json

import pytest

from matchtrader.capture import CaptureStore
from matchtrader.capture.pamm_publisher import IN_FLIGHT, PammPublisher, is_published
from matchtrader.capture.router import CaptureRouter
from matchtrader.capture.verified import classify
from matchtrader.models.position import Position
from tests.capture.test_verified import destination_quantity, observation, snapshot

URL = "https://tradingbox.pro/api/hcamm/events"
KEY = "fake-tradingbox-key"


class Forwarder:
    """Only the surface the publisher consumes: ticket(), url, api_key, auth_header and send."""

    def __init__(self, *, enabled=True, live=True, url=URL, api_key=KEY, status=200, error=None):
        self.enabled, self.live, self.url, self.api_key = enabled, live, url, api_key
        self.auth_header = "X-HCAMM-Key"
        self.status, self.error = status, error
        self.sent = []

    def ticket(self):
        return 1, self.enabled, self.live

    def send(self, url, headers, body, **kwargs):
        self.sent.append((url, headers, body))
        if self.error:
            raise self.error
        return self.status, "OK", [("Content-Type", "application/json")], b"{}"


def verified(**overrides):
    fields = {"trade_id": "t1", "destination_observations": [observation(open_time_millis=1789000000000)]}
    fields.update(overrides)
    return snapshot(**fields)


def publisher(tmp_path, forwarder):
    store = CaptureStore(tmp_path)
    return store, PammPublisher(store, lambda: forwarder)


def publications(store):
    return store.db.execute("SELECT COUNT(*) FROM pamm_publications").fetchone()[0]


def test_publishing_is_off_unless_the_forwarder_is_enabled_live_with_url_and_key(tmp_path):
    store = CaptureStore(tmp_path)
    assert PammPublisher(store, lambda: None).enabled() is False
    for off in (Forwarder(enabled=False), Forwarder(live=False), Forwarder(url=""), Forwarder(api_key="")):
        pamm = PammPublisher(store, lambda off=off: off)
        assert pamm.enabled() is False
        assert pamm.publish(verified()) is None and pamm.sweep([verified()]) == [] and off.sent == []
    assert PammPublisher(store, lambda: Forwarder()).enabled() is True
    assert publications(store) == 0
    store.close()


@pytest.mark.parametrize("unverified", [
    snapshot(trade_id="candidate", links=[{"side": "source", "kind": "order", "native_id": "o1"}]),
    snapshot(trade_id="write-response-only"),
    snapshot(trade_id="read-back-without-time", destination_observations=[observation()]),
    snapshot(trade_id="wrong-reader",
             destination_observations=[observation(reader="write_response", open_time_millis=1)]),
    snapshot(trade_id="uncertain", state="uncertain",
             links=[{"side": "source", "kind": "order", "native_id": "o1"}]),
])
def test_anything_short_of_verified_is_never_published(tmp_path, unverified):
    forwarder = Forwarder()
    store, pamm = publisher(tmp_path, forwarder)
    assert classify(unverified)["verified"] is False
    assert pamm.publish(unverified) is None and pamm.sweep([unverified]) == []
    assert forwarder.sent == [] and publications(store) == 0
    store.close()


def test_verified_open_is_published_once_through_the_forwarder_transport(tmp_path):
    forwarder = Forwarder()
    store, pamm = publisher(tmp_path, forwarder)
    row = pamm.publish(verified(source="P01", lots="0.02"))
    assert row["upstream_status"] == 200 and row["error_class"] == "" and is_published(row)
    ((url, headers, body),) = forwarder.sent
    assert url == URL and ("X-HCAMM-Key", KEY) in headers and ("Content-Type", "application/json") in headers
    payload = json.loads(body)
    assert payload["kind"] == "verified_trade" and payload["trade_id"] == "t1" and payload["verified"] is True
    assert payload["state"] == "verified_open" and payload["destination_position_ids"] == ["p1"]
    assert payload["broker_open_time_millis"] == 1789000000000 and payload["source"] == "P01"
    assert payload["lots"] == "0.02" and payload["read_back"]["reader"] == "open_positions"
    # Already published: neither a direct call nor a sweep sends again.
    assert pamm.publish(verified()) is None and pamm.sweep([verified()]) == []
    assert len(forwarder.sent) == 1 and publications(store) == 1
    assert pamm.publications(["t1"])["t1"]["upstream_status"] == 200
    store.close()


def test_verified_closed_is_published_with_its_closed_state(tmp_path):
    forwarder = Forwarder()
    store, pamm = publisher(tmp_path, forwarder)
    closed = verified(
        state="resolved", quantities=[destination_quantity("0.02")],
        destination_observations=[observation(reader="closed_positions", open_time_millis=1, volume="0.02")],
    )
    assert classify(closed)["state"] == "verified_closed"
    assert is_published(pamm.publish(closed))
    assert json.loads(forwarder.sent[0][2])["state"] == "verified_closed"
    store.close()


def test_a_failed_publication_is_recorded_and_never_retried(tmp_path):
    forwarder = Forwarder(error=OSError("upstream detail"))
    store, pamm = publisher(tmp_path, forwarder)
    trade = verified()
    before = json.dumps(trade, sort_keys=True)
    row = pamm.publish(trade)
    assert row["upstream_status"] is None and row["error_class"] == "OSError" and not is_published(row)
    assert json.dumps(trade, sort_keys=True) == before and classify(trade)["state"] == "verified_open"
    # The attempt row itself blocks a second publish, by hand or by sweep, even once the wire is back.
    forwarder.error = None
    assert pamm.publish(trade) is None and pamm.sweep([trade]) == [] and len(forwarder.sent) == 1
    stored = pamm.publications(["t1"])["t1"]
    assert stored["upstream_status"] is None and stored["error_class"] == "OSError"
    assert stored["error_class"] != IN_FLIGHT and stored["duration_ms"] is not None
    store.close()


def test_a_non_2xx_upstream_answer_is_an_attempt_not_a_publication(tmp_path):
    forwarder = Forwarder(status=422)
    store, pamm = publisher(tmp_path, forwarder)
    row = pamm.publish(verified())
    assert row["upstream_status"] == 422 and not is_published(row)
    assert pamm.publish(verified()) is None and len(forwarder.sent) == 1
    store.close()


def test_a_failed_publication_never_changes_a_real_verified_trade(tmp_path, event, broker, route):
    store = CaptureStore(tmp_path)
    router = CaptureRouter(store, route)
    router.armed = router.demo_verified = True
    result = router.receive(event.model_copy(update={"order_type": "MARKET"}).model_dump(), broker, "demo")
    assert result["status"] == "accepted"
    trade_id = result["trade_id"]
    store.observe_positions(trade_id, "demo", [Position(
        id="position1", symbol="EURUSD", side="BUY", volume=".01", openPrice="1.15", openTimeMillis=1789000000000,
    )])
    (before,) = store.mapping_view("demo")
    assert classify(before)["state"] == "verified_open"
    forwarder = Forwarder(error=ConnectionError("down"))
    pamm = PammPublisher(store, lambda: forwarder)
    (row,) = pamm.sweep(store.mapping_view("demo"))
    assert row["trade_id"] == trade_id and row["error_class"] == "ConnectionError"
    (after,) = store.mapping_view("demo")
    assert after == before and classify(after)["state"] == "verified_open"
    assert store.trade(trade_id)["state"] == "open"
    assert store.db.execute("SELECT COUNT(*) FROM outcome_reasons").fetchone()[0] == 0
    store.close()


def test_an_invalid_forwarder_url_refuses_before_any_row_or_send(tmp_path):
    forwarder = Forwarder(url="https://evil.example/api/hcamm/events")
    store, pamm = publisher(tmp_path, forwarder)
    with pytest.raises(ValueError):
        pamm.publish(verified())
    assert forwarder.sent == [] and publications(store) == 0
    store.close()


def test_publications_lookup_is_scoped_to_the_requested_ids(tmp_path):
    forwarder = Forwarder()
    store, pamm = publisher(tmp_path, forwarder)
    pamm.publish(verified())
    assert pamm.publications([]) == {} and pamm.publications(["", None]) == {}
    assert set(pamm.publications(["t1", "other", "t1"])) == {"t1"}
    store.close()


@pytest.mark.parametrize("row, published", [
    (None, False), ({}, False), ({"upstream_status": None}, False), ({"upstream_status": "200"}, False),
    ({"upstream_status": 199}, False), ({"upstream_status": 200}, True), ({"upstream_status": 299}, True),
    ({"upstream_status": 300}, False), ({"upstream_status": 502}, False),
])
def test_is_published_counts_only_a_2xx_integer_status(row, published):
    assert is_published(row) is published
