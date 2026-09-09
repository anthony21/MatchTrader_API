import matchtrader.core as package


def test_core_package_import_is_available():
    assert package.__package__ == "matchtrader.core"
