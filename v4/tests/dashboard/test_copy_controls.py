"""Copy controls: paper by default with every source off; a post is the whole desired state."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from matchtrader.capture.event import CaptureEvent
from matchtrader.capture.route import RouteConfig
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


def test_roundtrip_is_atomic_keeps_sources_and_never_reloads_live(tmp_path):
    path = tmp_path / "controls" / "copy-controls.json"
    value = CopyControls.model_validate({"mode": "live", "sources": {"P01": True, "X17": False, "MANUAL": True}})
    save_controls(path, value)
    assert json.loads(path.read_text()) == value.model_dump(mode="json")  # the file records what was posted
    assert [p.name for p in path.parent.iterdir()] == [path.name]  # no temp file left behind
    loaded = load_controls(path)
    assert loaded.sources == value.sources  # per-source switches persist exactly
    assert loaded.mode == "paper"  # the master mode does not: live never survives a load
    paper = CopyControls.model_validate({"mode": "paper", "sources": {"X17": True}})
    save_controls(path, paper)
    assert load_controls(path) == paper


def test_live_resets_to_paper_on_every_process_start(settings, tmp_path):
    path = tmp_path / "copy-controls.json"
    path.write_text(json.dumps({"mode": "live", "sources": {"P01": True, "X17": True, "MANUAL": True}}))
    assert load_controls(path).mode == "paper"
    controller = DashboardController(settings, tmp_path)
    try:
        # Same rule as signal copying: a restart is unattended, so it comes back in paper with the
        # source switches exactly as the owner left them.
        assert controller.copy_controls_view() == {"mode": "paper", "sources": {"P01": True, "X17": True, "MANUAL": True}}
        assert json.loads(path.read_text())["mode"] == "live"  # the file is evidence, not authority
        # Going live is a deliberate action in the running session, and it works.
        assert controller.configure_copy_controls({"mode": "live", "sources": {"P01": True}})["mode"] == "live"
    finally:
        controller.close()
    again = DashboardController(settings, tmp_path)
    try:
        assert again.copy_controls_view() == {"mode": "paper", "sources": {"P01": True, "X17": False, "MANUAL": False}}
    finally:
        again.close()


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


class RaisingBroker:
    """A connected, verified destination whose every broker method fails the test on access.
    `connection` is a real attribute so the controller reads it as a verified owner session."""

    def __init__(self, account_id):
        self.connection = SimpleNamespace(session_expires_at=None, account_id=account_id)

    def close(self):
        pass

    def __getattr__(self, name):
        raise AssertionError(f"Broker method {name} reached from the capture path; automatic dispatch must be impossible")


def test_the_armed_router_door_is_closed_and_arrival_never_dispatches(settings, tmp_path):
    """The old automatic path under the most permissive state it ever required: capture running,
    a write-enabled session connected to the route's demo destination, every copy source on and
    the mode live. Arming is refused and an arriving ACCEPTED CREATE produces no broker call."""
    route = RouteConfig(
        machine="qt", connection_id="connection", account_id="source", destination_account="123",
        sources=["P01", "X17", "MANUAL"], exclusive_destination=True, legacy_route_disabled=True,
        symbols={"EURUSD": {"destination": "EURUSD", "quantity_multiplier": "1", "max_lots": "10",
                            "same_price_scale": True}},
    )
    controller = DashboardController(settings, tmp_path, route=route, interactive_copying=True)
    try:
        assert controller.settings.enable_writes
        controller.api = RaisingBroker("123")
        controller.connection = "connected"
        controller.native.demo_verified = True
        controller.start_capture()
        controller.configure_copy_controls({"mode": "live", "sources": {"P01": True, "X17": True, "MANUAL": True}})
        with pytest.raises(ValueError, match=r"Automatic dispatch is disabled.*POST /api/trades/send"):
            controller.set_copying(True)
        assert controller.native.armed is False and controller.native.armed_at is None
        assert controller.status()["copying"] is False and controller.status()["mode"] == "capture"
        for source in SOURCES:
            result = controller.receive_native(
                signal(source, event_id=f"arrival-{source}", order_id=f"order-{source}").model_dump(mode="json"))
            assert result["status"] == "held" and result["broker_order_id"] == "" and result["broker_position_id"] == ""
        store = controller.native_store
        assert store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == len(SOURCES)
        assert store.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert store.db.execute("SELECT COUNT(*) FROM action_history").fetchone()[0] == 0
        assert all(row["state"] == "observed" and row["destination"] == ""
                   for row in store.db.execute("SELECT state, destination FROM trades"))
        # Disarming remains available so every existing shutdown path keeps working.
        assert controller.set_copying(False)["copying"] is False
        controller.stop()
    finally:
        controller.api = None
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
        # The restart came back in paper although the file says live; live is re-chosen explicitly.
        assert interactive.copy_controls_view()["mode"] == "paper"
        interactive.configure_copy_controls({"mode": "live", "sources": {"MANUAL": True}})
        with pytest.raises(ValueError, match="Connect the destination"):
            interactive.send_trade({"trade_id": trade_id, "volume": "0.25"})
        assert interactive.native_store.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert interactive.native_store.db.execute("SELECT COUNT(*) FROM paper_sends").fetchone()[0] == 0
    finally:
        interactive.close()
