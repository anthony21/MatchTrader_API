import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from matchtrader.dashboard.controller import DashboardController
from matchtrader.dashboard.copy_settings import CopySettings, load_settings, save_settings
from matchtrader.models.account import Account


def payload():
    return {
        "route": {
            "machine": "qt",
            "connection_id": "ctrader",
            "account_id": "source",
            "destination_account": "123",
            "sources": ["P01"],
            "exclusive_destination": True,
            "legacy_route_disabled": True,
            "symbols": {
                "EUR/USD": {
                    "destination": "EURUSD",
                    "quantity_multiplier": "1",
                    "max_lots": "1",
                    "same_price_scale": True,
                }
            },
        },
        "csv_limit": 25,
    }


def test_atomic_settings_roundtrip_never_persists_arming(tmp_path):
    path = tmp_path / "settings.json"
    assert load_settings(path) is None
    value = CopySettings.model_validate(payload())
    save_settings(path, value)
    assert load_settings(path) == value
    assert "armed" not in json.loads(path.read_text())
    for bad in [dict(payload(), csv_limit=0), dict(payload(), armed=True)]:
        with pytest.raises(ValidationError):
            CopySettings.model_validate(bad)


def test_runtime_settings_keep_existing_connection_and_restart_disarmed(settings, tmp_path):
    class Session:
        def __init__(self, settings):
            self.connection = SimpleNamespace(session_expires_at=None)

        def login(self):
            return SimpleNamespace(tradingAccounts=[Account(tradingAccountId="123", offer={"demo": True})])

        def close(self):
            pass

    c = DashboardController(settings, tmp_path, interactive_copying=True, api_factory=Session)
    try:
        assert c.settings.enable_writes and not c.native.armed
        c.connect("123")
        session = c.api
        assert c.configure_copying(payload())["route"]["sources"] == ["P01"]
        assert c.api is session and c.status()["connection"] == "connected"
        assert c.native_store.limit == 25
        # Even with a connected, write-enabled session and a saved route - the exact state that
        # used to arm the router - automatic dispatch is refused and settings stay editable.
        c.start_capture()
        with pytest.raises(ValueError, match="Automatic dispatch is disabled"):
            c.set_copying(True)
        assert c.native.armed is False and c.native.armed_at is None
        assert c.configure_copying(payload())["route"]["sources"] == ["P01"]
        assert c.set_copying(False)["copying"] is False  # disarming is still an accepted no-op
    finally:
        c.close()
    c = DashboardController(settings, tmp_path, interactive_copying=True)
    try:
        assert c.native.route.sources == ["P01"] and not c.native.armed
        assert c.native_store.limit == 25
    finally:
        c.close()
