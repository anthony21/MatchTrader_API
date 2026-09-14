from decimal import Decimal

import pytest

from matchtrader.signals import SymbolMap, SymbolMapping
from tests.signals.helpers import symbols


def test_symbol_map_is_a_plain_lookup_that_round_trips_its_own_file(tmp_path):
    table = symbols()
    assert table.lookup("US TECH 100").destination == "NAS100" and table.lookup("EURUSD") is None
    table.save(tmp_path / "symbol-map.json")
    loaded = SymbolMap.load(tmp_path / "symbol-map.json")
    assert loaded.lookup("US TECH 100").lots == Decimal("0.2") and len(loaded) == 1
    assert len(SymbolMap.load(tmp_path / "missing.json")) == 0


def test_one_store_serves_every_lane_and_persists_each_replacement(tmp_path):
    from matchtrader.signals import SymbolMapStore
    store = SymbolMapStore(tmp_path / "symbol-map.json")
    assert len(store.map) == 0
    store.replace(symbols())
    other_view = store                                     # a second lane holds the same object
    assert other_view.map.lookup("US TECH 100").destination == "NAS100"
    assert SymbolMapStore(tmp_path / "symbol-map.json").map.lookup("US TECH 100").lots == Decimal("0.2")


def test_a_mapping_needs_a_destination_a_positive_size_and_a_known_order_handling():
    with pytest.raises(ValueError):
        SymbolMapping(destination="", lots=Decimal("0.1"))
    with pytest.raises(ValueError):
        SymbolMapping(destination="X", lots=Decimal("0"))
    with pytest.raises(ValueError):
        SymbolMapping(destination="X", lots=Decimal("0.1"), order_type="TRAILING")
    assert SymbolMapping(destination="X", lots=Decimal("0.1")).order_type == "SOURCE"
    with pytest.raises(ValueError):
        SymbolMap.model_validate({"X": {"destination": "Y", "lots": "1", "unknown": 1}})
