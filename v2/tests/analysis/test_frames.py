from decimal import Decimal

import pandas as pd
import pytest

from matchtrader.analysis.frames import to_frame
from matchtrader.models.position import Position


def test_parent_child_exposure_not_double_counted():
    p = Position(
        id="P",
        symbol="XAUUSD",
        side="BUY",
        volume="1",
        openPrice="2400",
        positions=[{"id": "C", "symbol": "XAUUSD", "side": "BUY", "volume": "1", "openPrice": "2400"}],
    )
    frame = to_frame([p], numeric=["volume"])
    assert len(frame) == 1
    assert frame.volume.sum() == 1
    assert p.volume == Decimal(1)


def test_naive_timezone_explicit_and_invalid_numeric_not_silently_dropped():
    with pytest.raises(ValueError, match="naive_timezone"):
        to_frame([{"time": "2026-09-07T12:00:00"}], timestamps=["time"])
    frame = to_frame([{"time": "2026-09-07T12:00:00"}], timestamps=["time"], naive_timezone="America/Chicago")
    assert frame.time.iloc[0] == pd.Timestamp("2026-09-07T17:00:00Z")
    with pytest.raises(ValueError):
        to_frame([{"profit": "bad"}], numeric=["profit"])
