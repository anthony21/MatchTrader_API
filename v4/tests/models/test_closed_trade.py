from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.models.closed_trade import ClosedTrade


def test_closed_trade_shape_and_forward_compatible_fields():
    obj = ClosedTrade.model_validate(
        {
            "id": "W1",
            "symbol": "EURUSD",
            "side": "BUY",
            "volume": "0.01",
            "openPrice": "1.10",
            "closePrice": "1.11",
            "openTime": "2026-09-07T10:00:00Z",
            "time": "2026-09-07T11:00:00Z",
            "profit": "10",
            "netProfit": "9",
            "uid": "W1_close1",
            "closingOrderID": "W2",
            "closeReason": "CLOSE_REASON_PARTIAL",
            "brokerExtension": "preserved",
        }
    )
    assert obj.model_dump()["brokerExtension"] == "preserved"
    assert isinstance(obj.volume, Decimal)
    with pytest.raises(ValidationError):
        ClosedTrade.model_validate({})
