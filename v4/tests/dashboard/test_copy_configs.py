from decimal import Decimal

import pytest

from matchtrader.dashboard.copy_configs import CopyConfig, CopyConfigStore


def cfg(**changes):
    base = dict(id="c1", name="MAD to GTR", machine_id="HCAMM_MAD", source="r01Auto",
                destination_broker="GTR", destination_account="644953",
                sizing="dollar", sizing_value=Decimal("5"))
    return CopyConfig(**{**base, **changes})


def test_a_config_matches_only_its_machine_and_source():
    c = cfg(additional_sources=["panel"])
    assert c.matches("HCAMM_MAD", "r01Auto")
    assert c.matches("HCAMM_MAD", "panel")          # an additional source also matches
    assert not c.matches("HCAMM_MIKE", "r01Auto")   # a different machine does not
    assert not c.matches("HCAMM_MAD", "chain")      # a different source does not


def test_store_persists_upserts_toggles_and_only_lists_enabled_matches(tmp_path):
    path = tmp_path / "copy-configs.json"
    store = CopyConfigStore(path)
    assert store.list() == []
    store.upsert(cfg())
    store.upsert(cfg(id="c2", name="MAD to AQF", destination_broker="AQF", destination_account="276954"))
    assert {c.id for c in store.list()} == {"c1", "c2"}
    # Nothing is enabled yet, so nothing matches even the right machine/source.
    assert store.matching("HCAMM_MAD", "r01Auto") == []
    store.set_state("c1", enabled=True, mode="live")
    assert store.get("c1").enabled and store.get("c1").mode == "live"
    matched = store.matching("HCAMM_MAD", "r01Auto")
    assert [c.id for c in matched] == ["c1"]                 # only the enabled one
    store.set_state("c2", enabled=True)
    assert {c.id for c in store.matching("HCAMM_MAD", "r01Auto")} == {"c1", "c2"}   # fan-out to both
    # A fresh store reads the saved file back.
    assert {c.id for c in CopyConfigStore(path).list()} == {"c1", "c2"}
    store.delete("c1")
    assert {c.id for c in store.list()} == {"c2"}
    with pytest.raises(ValueError, match="Unknown"):
        store.delete("c1")


def test_percent_sizing_needs_a_value_but_lots_does_not():
    lots = cfg(sizing="lots", sizing_value=None)
    assert lots.sizing == "lots"
    with pytest.raises(ValueError):
        cfg(sizing_value=Decimal("0"))   # a non-positive sizing value is rejected
