import matchtrader.analysis as package


def test_analysis_package_import_is_available():
    assert package.__package__ == "matchtrader.analysis"
