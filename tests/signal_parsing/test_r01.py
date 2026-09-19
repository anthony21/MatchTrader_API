from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.signal_parsing.r01 import R01Signal


def test_complete_source_shape_preserves_names_precision_and_extensions(r01_payload):
    assert len(r01_payload) == len(R01Signal.model_fields) == 43
    r01_payload.update(robotName="BTC scalper", brokerOrderId="source-order",
                       brokerPositionId="source-position", instrument={"tickSize": 0.01},
                       futureContext={"custom": True})
    signal = R01Signal.model_validate(r01_payload)
    assert signal.timestampUtc == "2026-09-18T22:35:27.7684986Z"
    assert signal.entry == Decimal("81194.12000000002")
    assert signal.machineId == "test-machine" and signal.robotName == "BTC scalper"
    assert signal.brokerOrderId == "source-order" and signal.brokerPositionId == "source-position"
    assert signal.model_dump()["futureContext"] == {"custom": True}
    assert signal.instrument == {"tickSize": 0.01}


@pytest.mark.parametrize(("key", "value"), [
    ("entry", True), ("entry", "81194"), ("entry", float("inf")),
    ("dryRun", "false"), ("sequence", 1.5), ("sequence", True),
    ("timestampUtc", "2026-09-18T22:35:27"), ("machineId", ""),
])
def test_invalid_source_types_are_not_silently_coerced(r01_payload, key, value):
    r01_payload[key] = value
    with pytest.raises(ValidationError):
        R01Signal.model_validate(r01_payload)


def test_missing_fields_are_reported(r01_payload):
    del r01_payload["ladderArm"]
    with pytest.raises(ValidationError) as error:
        R01Signal.model_validate(r01_payload)
    assert error.value.errors()[0]["loc"] == ("ladderArm",)
