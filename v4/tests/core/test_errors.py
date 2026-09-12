from matchtrader.core.errors import APIError, MatchTraderError, UnknownOutcomeError


def test_exception_contract():
    error = APIError("Unavailable", 503)
    assert error.status_code == 503
    assert str(error) == "Unavailable"
    assert error.reason is None
    assert isinstance(error, MatchTraderError)
    assert isinstance(UnknownOutcomeError("unknown"), APIError)


def test_reason_is_keyword_only_and_optional():
    reason = {"origin": "broker", "code": "HTTP 400", "summary": "", "evidence": "broker write response"}
    error = APIError("Rejected", 400, reason=reason)
    assert error.reason is reason
    assert UnknownOutcomeError("unknown", reason=reason).reason is reason
