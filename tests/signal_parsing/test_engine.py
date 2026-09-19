import json
from decimal import Decimal

import pytest
from pydantic import BaseModel

from matchtrader.dashboard.signals import SignalHub
from matchtrader.signal_parsing.engine import ParsingEngine, default_engine


def test_batch_isolation_and_shape_errors_preserve_valid_source(r01_payload):
    bad = {**r01_payload, "entry": "bad"}
    result = default_engine().parse([
        r01_payload, bad, {"source": "future"}, 42,
        {**r01_payload, "orderType": "unknown"},
        {**r01_payload, "source": "r01Local", "kind": "refused"},
    ])
    assert [r.status for r in result] == ["parsed", "invalid", "unsupported", "invalid", "parsed", "parsed"]
    assert result[0].shapes["r01OrderShape"].orderSide == "SELL"
    assert result[1].issues[0]["field"] == "entry"
    assert result[4].signal is not None and result[4].shapes == {}
    assert result[4].issues[0]["stage"] == "r01OrderShape"
    assert result[5].signal.kind == "refused" and result[5].shapes == {}
    assert [r.index for r in result] == list(range(6))


def test_raw_decimal_precision_and_complete_record(r01_payload):
    raw = json.dumps(r01_payload).replace("81194.12000000002", "81194.120000000020123")
    result = default_engine().parse_raw(raw)[0]
    assert result.signal.entry == Decimal("81194.120000000020123")
    record = result.record()
    assert record["signal"]["ladderGrade"] == "PRIME"
    assert record["signal"]["ladderArm"] == "r5:b8|PRIME|"
    assert record["shapes"]["r01OrderShape"]["price"] == "81194.120000000020123"
    assert json.loads(json.dumps(record)) == record


@pytest.mark.parametrize("raw", ["text", '{"entry": NaN}', '{"entry": Infinity}'])
def test_invalid_json_has_diagnostic_result(raw):
    result = default_engine().parse_raw(raw)[0]
    assert result.status == "invalid" and result.issues[0]["stage"] == "json"


def test_new_source_can_register_its_model_and_shapes():
    class FutureSignal(BaseModel):
        source: str
        value: int

    engine = ParsingEngine()
    engine.register("future", FutureSignal, shapes={"futureShape": lambda signal: signal})
    result = engine.parse({"source": "future", "value": 8})[0]
    assert result.shapes["futureShape"].value == 8
    with pytest.raises(ValueError, match="already registered"):
        engine.register("future", FutureSignal, shapes={})


def test_journal_persists_raw_batch_and_shapes_for_push_and_reopen(tmp_path, r01_payload):
    path = tmp_path / "signals.sqlite3"
    raw = json.dumps([r01_payload, {**r01_payload, "source": "r01Local", "kind": "refused"}])
    hub = SignalHub(path)
    try:
        queue = hub.subscribe()
        queue.get()
        ack = hub.publish(raw)
        event = queue.get()["event"]
        assert event["id"] == ack["id"] and event["raw"] == raw
        assert event["signals"][0]["shapes"]["r01OrderShape"]["orderSide"] == "SELL"
        assert event["signals"][1]["signal"]["kind"] == "refused"
        assert event["signals"][1]["shapes"] == {}
    finally:
        hub.close()
    reopened = SignalHub(path)
    try:
        assert reopened.recent()[0] == event
    finally:
        reopened.close()
