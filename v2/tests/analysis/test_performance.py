import pytest

from matchtrader.analysis.performance import summarize_closed_operations


def test_ordered_operations_breakevens_and_initial_loss_drawdown():
    records = [
        {"time": "2026-01-01T00:02:00Z", "netProfit": "20"},
        {"time": "2026-01-01T00:01:00Z", "netProfit": "-10"},
        {"time": "2026-01-01T00:03:00Z", "netProfit": "0"},
    ]
    result = summarize_closed_operations(records)
    assert result["operations"] == 3
    assert result["wins"] == 1 and result["losses"] == 1 and result["breakevens"] == 1
    assert result["profit_factor"] == 2
    assert result["net_profit"] == 10
    assert result["realized_pnl_drawdown"] == 10


def test_empty_and_nonfinite():
    assert summarize_closed_operations([])["operations"] == 0
    with pytest.raises(ValueError):
        summarize_closed_operations([{"time": "2026-01-01T00:00:00Z", "netProfit": "NaN"}])
