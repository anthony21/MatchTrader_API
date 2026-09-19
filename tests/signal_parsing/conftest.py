import pytest


@pytest.fixture
def r01_payload():
    # Full wire shape from the owner's supplied example, with test identity values.
    return {
        "mode": "relay", "source": "r01Auto", "kind": "intent",
        "label": "R01_BTCUSD_short_test", "brokerOrderId": "", "brokerPositionId": "",
        "rangeKind": "norm", "wasBeyond": False, "wallId": "wall-test",
        "boxInstanceId": "box-test", "symbol": "BTCUSD", "side": "short",
        "entry": 81194.12000000002, "stopLoss": 81209.35562500003,
        "takeProfit": 81163.64875000001, "ladderGrade": "PRIME", "stamp": 88.5,
        "l2Class": "", "l2Word": "", "l2DbandDigit": 0, "l2BirthRank": 0,
        "l2ChurnBand": "-", "l2PosInWin": False, "tapHash": "test-hash",
        "clientEventId": "test-event", "refClientEventId": "", "tier": "", "cell": "",
        "rfx": "STALE", "inverted": False, "orderType": "limit", "volume": 0,
        "grade": "", "ladderArm": "r5:b8|PRIME|", "detail": "r01 regrade: regrade",
        "dryRun": False, "machineId": "test-machine", "robotName": "",
        "accountId": "", "connectionName": "", "timestampUtc": "2026-09-18T22:35:27.7684986Z",
        "sequence": 131, "instrument": None,
    }
