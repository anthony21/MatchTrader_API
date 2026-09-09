from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from matchtrader.capture import CaptureStore
from matchtrader.capture.router import CaptureRouter
from matchtrader.models.position import Position


def configured(tmp_path, route):
    router = CaptureRouter(CaptureStore(tmp_path), route)
    router.armed = router.demo_verified = True
    return router


def test_p01_copy_uses_submitted_brackets_and_manual_cancel_follows_mapping(tmp_path, route, event, broker):
    route.sources = ["P01"]
    router = configured(tmp_path, route)
    event = event.model_copy(update={"source": "P01", "source_label": "P01RR_120001_5"})
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "accepted" and result["broker_order_id"] == "aqua1"
    assert broker.calls[0][1]["slPrice"] == event.sl
    cancel = event.model_copy(
        update={"action": "CANCEL", "event_id": "cancel", "request_id": "c1", "source": "UNKNOWN"}
    )
    assert router.receive(cancel.model_dump(), broker, "demo")["status"] == "accepted"
    router.store.close()


def test_enable_does_not_replay_queued_off_period(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    router.armed_at = datetime.now(UTC)
    assert router.receive(event.model_dump(), broker, "demo")["status"] == "held"
    assert not broker.calls
    router.store.close()


def test_create_edit_cancel_same_id_with_duplicate_delivery(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "accepted"
    assert router.receive(event.model_dump(), broker, "demo")["duplicate"]
    replay = event.model_copy(update={"event_id": "new-event-id"})
    assert router.receive(replay.model_dump(), broker, "demo")["status"] == "held"
    for i, action in enumerate(["EDIT", "CANCEL"], 2):
        updated = event.model_copy(update={"event_id": f"e{i}", "request_id": f"run:{i}", "action": action})
        accepted = router.receive(updated.model_dump(), broker, "demo")
        assert accepted["trade_id"] == result["trade_id"] and accepted["status"] == "accepted"
    assert [c[0] for c in broker.calls] == ["CREATE", "EDIT", "CANCEL"]
    assert broker.calls[1][1]["id"] == "aqua1"
    trade = router.store.trade(result["trade_id"])
    assert trade["state"] == "resolved" and trade["resolved_at"]
    router.store.close()


def test_uncertain_write_never_retried_after_restart(tmp_path, route, event, broker):
    router = configured(tmp_path, route)

    def timeout(**kwargs):
        broker.calls.append(("CREATE", kwargs))
        raise TimeoutError()

    broker.create_pending_order = timeout
    assert router.receive(event.model_dump(), broker, "demo")["status"] == "uncertain"
    router.store.close()
    router = configured(tmp_path, route)
    assert (
        router.receive(event.model_copy(update={"event_id": "different"}).model_dump(), broker, "demo")[
            "status"
        ]
        == "held"
    )
    assert len(broker.calls) == 1
    router.store.close()


@pytest.mark.parametrize(
    "change",
    [
        {"snapshot": True},
        {"source": "UNKNOWN"},
        {"account_id": "other"},
        {"quantity": Decimal("1000")},
        {"order_type": "STOP_LIMIT"},
        {"brackets_absolute": False},
        {"order_id": ""},
        {"action": "CANCEL"},
        {"symbol": "ES"},
        {"sl": Decimal("1.16")},
        {"emitted_at": datetime.now(UTC) - timedelta(minutes=1)},
    ],
)
def test_holds_before_any_broker_write(tmp_path, route, event, broker, change):
    router = configured(tmp_path, route)
    assert router.receive(event.model_copy(update=change).model_dump(), broker, "demo")["status"] == "held"
    assert not broker.calls
    router.store.close()


def test_snapshots_signals_and_request_intent_cannot_place_orders(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    for kind in ["ORDER", "FILL", "POSITION", "SIGNAL", "REQUEST", "REJECTED"]:
        result = router.receive(
            event.model_copy(update={"event_id": kind, "kind": kind}).model_dump(), broker, "demo"
        )
        assert result["status"] == "captured"
    assert not broker.calls
    router.store.close()


def test_market_fill_links_source_position_and_close(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    event = event.model_copy(update={"order_type": "MARKET"})
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "accepted"
    broker.positions = [Position(id="position1", symbol="EURUSD", side="BUY", volume=".01", openPrice="1.15")]
    router.receive(
        event.model_copy(
            update={"event_id": "fill", "kind": "FILL", "position_id": "qtposition"}
        ).model_dump(),
        broker,
        "demo",
    )
    close = event.model_copy(
        update={
            "event_id": "close",
            "request_id": "run:2",
            "order_id": "",
            "position_id": "qtposition",
            "action": "CLOSE",
        }
    )
    assert router.receive(close.model_dump(), broker, "demo")["status"] == "accepted"
    assert broker.calls[-1][1]["positionId"] == "position1"
    assert router.store.trade(result["trade_id"])["state"] == "resolved"
    router.store.close()
