from matchtrader.core.errors import APIError, MatchTraderError, UnknownOutcomeError


def test_exception_contract():
    error = APIError("Unavailable", 503)
    assert error.status_code == 503
    assert str(error) == "Unavailable"
    assert isinstance(error, MatchTraderError)
    assert isinstance(UnknownOutcomeError("unknown"), APIError)
