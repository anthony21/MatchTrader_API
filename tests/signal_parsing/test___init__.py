from matchtrader.signal_parsing import R01OrderShape, R01Signal, default_engine


def test_public_parser_api(r01_payload):
    result = default_engine().parse(r01_payload)[0]
    assert isinstance(result.signal, R01Signal)
    assert isinstance(result.shapes["r01OrderShape"], R01OrderShape)
