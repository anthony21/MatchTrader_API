"""Copy controls: paper by default with every source off; a post is the whole desired state."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from matchtrader.capture.event import CaptureEvent
from matchtrader.dashboard.controller import DashboardController
from matchtrader.dashboard.copy_controls import SOURCES, CopyControls, load_controls, save_controls

OFF = {"P01": False, "X17": False, "MANUAL": False}


def signal(source="MANUAL", **overrides):
    fields = {
        "event_id": "event1", "machine": "qt", "connection_id": "connection", "account_id": "source",
        "order_id": "order1", "request_id": "run:1", "emitted_at": datetime.now(UTC), "kind": "ACCEPTED",
        "action": "CREATE", "source": source, "symbol": "EURUSD", "side": "BUY", "order_type": "LIMIT",
        "quantity": "1", "price": "1.15000", "sl": "1.14980", "tp": "1.16",
    }
    fields.update(overrides)
    return CaptureEvent(**fields)


def test_defaults_are_paper_with_every_source_off(tmp_path):
    for value in (CopyControls(), load_controls(tmp_path / "missing.json")):
        assert value.mode == "paper"
        assert value.model_dump() == {"mode": "paper", "sources": OFF}
        assert not any(value.enabled(source) for source in SOURCES)


def test_only_the_three_governed_sources_can_ever_be_enabled():
    value = CopyControls.model_validate({"mode": "live", "sources": {"P01": True, "X17": True, "MANUAL": True}})
    assert all(value.enabled(source) for source in SOURCES)
    for other in ("R01", "UNKNOWN", "", None, "p01", "sources", "mode", "model_config"):
        assert value.enabled(other) is False


def test_roundtrip_is_atomic_and_exact(tmp_path):
    path = tmp_path / "controls" / "copy-controls.json"
    value = CopyControls.model_validate({"mode": "live", "sources": {"P01": True, "X17": False, "MANUAL": True}})
    save_controls(path, value)
    assert load_controls(path) == value
    assert json.loads(path.read_text()) == value.model_dump(mode="json")
    assert [p.name for p in path.parent.iterdir()] == [path.name]  # no temp file left behind


@pytest.mark.parametrize("bad", [
    {"mode": "armed", "sources": {}},
    {"mode": "paper", "sources": {"R01": True}},
    {"mode": "paper", "sources": {}, "auto_send": True},
    {"mode": "paper", "sources": {"P01": "maybe"}},
    {"mode": "paper", "sources": {"P01": None}},
    {"mode": "paper", "sources": None},
    {"mode": None, "sources": {}},
    [],
])
def test_unknown_modes_sources_or_fields_are_refused(bad):
    with pytest.raises(ValidationError):
        CopyControls.model_validate(bad)


def test_controller_treats_a_post_as_the_whole_desired_state(settings, tmp_path):
    controller = DashboardController(settings, tmp_path)
    try:
        assert controller.copy_controls_view() == {"mode": "paper", "sources": OFF}
        everything = {"mode": "live", "sources": {"P01": True, "X17": True, "MANUAL": True}}
        assert controller.configure_copy_controls(everything) == everything
        # A replacement, not a patch: sources left out of the next post are off.
        assert controller.configure_copy_controls({"mode": "paper", "sources": {"X17": True}}) == {
            "mode": "paper", "sources": {"P01": False, "X17": True, "MANUAL": False}}
        with pytest.raises(ValidationError):
            controller.configure_copy_controls({"mode": "paper", "sources": {"X17": True}, "extra": 1})
        assert controller.copy_controls_view()["sources"]["X17"] is True  # a refused post changes nothing
        assert json.loads((tmp_path / "copy-controls.json").read_text()) == controller.copy_controls_view()
    finally:
        controller.close()
    reopened = DashboardController(settings, tmp_path)
    try:
        assert reopened.copy_controls_view() == {"mode": "paper", "sources": {"P01": False, "X17": True, "MANUAL": False}}
    finally:
        reopened.close()


def test_enabled_means_eligible_never_auto_send(settings, tmp_path):
    controller = DashboardController(settings, tmp_path)
    try:
        controller.configure_copy_controls({"mode": "live", "sources": {"P01": True, "X17": True, "MANUAL": True}})
        for source in SOURCES:
            result = controller.native.receive(signal(source, event_id=f"e-{source}", order_id=f"o-{source}").model_dump())
            assert result["status"] == "held" and result["broker_order_id"] == ""
        store = controller.native_store
        assert store.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert store.db.execute("SELECT COUNT(*) FROM paper_sends").fetchone()[0] == 0
        assert store.db.execute("SELECT COUNT(*) FROM action_history").fetchone()[0] == 0
        assert all(row["state"] == "observed" for row in store.db.execute("SELECT state FROM trades"))
    finally:
        controller.close()


def test_send_trade_gates_live_on_writes_and_a_verified_connection(settings, tmp_path):
    controller = DashboardController(settings, tmp_path)
    try:
        trade_id = controller.native.receive(signal().model_dump())["trade_id"]
        with pytest.raises(ValueError, match="trade id"):
            controller.send_trade({"volume": "0.25"})
        with pytest.raises(ValueError, match="trade id"):
            controller.send_trade("not-a-dict")
        controller.configure_copy_controls({"mode": "live", "sources": {"MANUAL": True}})
        # No route and not interactive: this dashboard session cannot write to the broker at all.
        with pytest.raises(ValueError, match="writes are disabled"):
            controller.send_trade({"trade_id": trade_id, "volume": "0.25"})
        assert controller.native_store.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    finally:
        controller.close()
    interactive = DashboardController(settings, tmp_path, interactive_copying=True)
    try:
        trade_id = interactive.native_store.db.execute("SELECT trade_id FROM trades").fetchone()[0]
        with pytest.raises(ValueError, match="Connect the destination"):
            interactive.send_trade({"trade_id": trade_id, "volume": "0.25"})
        assert interactive.native_store.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    finally:
        interactive.close()
