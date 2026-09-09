import matchtrader


def test_public_exports():
    assert set(matchtrader.__all__) == {"MatchTraderAPI", "Settings"}
