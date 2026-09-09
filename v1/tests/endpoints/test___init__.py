import matchtrader.endpoints as package


def test_endpoints_package_import_is_available():
    assert package.__package__ == "matchtrader.endpoints"
