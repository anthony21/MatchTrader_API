import matchtrader.models as package


def test_models_package_import_is_available():
    assert package.__package__ == "matchtrader.models"
