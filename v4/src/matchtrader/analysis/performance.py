"""Statistics over closing operations, not assumed full-trade round trips."""

import numpy as np

from .frames import to_frame


def summarize_closed_operations(records, *, naive_timezone=None):
    frame = to_frame(
        records, numeric=("netProfit", "volume"), timestamps=("time",), naive_timezone=naive_timezone
    )
    if frame.empty:
        return {
            "operations": 0,
            "wins": 0,
            "losses": 0,
            "breakevens": 0,
            "net_profit": 0.0,
            "win_rate": 0.0,
            "profit_factor": None,
            "realized_pnl_drawdown": 0.0,
        }
    required = {"netProfit", "time"}
    if not required <= set(frame):
        raise ValueError("Closing operations need netProfit and time")
    if frame["time"].isna().any():
        raise ValueError("Closing operations need a timestamp for ordering")
    frame = frame.sort_values("time", kind="stable")
    pnl = frame["netProfit"].to_numpy(dtype=float)
    if not np.isfinite(pnl).all():
        raise ValueError("P&L must contain finite numbers")
    equity = np.concatenate(([0.0], np.cumsum(pnl)))
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    return {
        "operations": len(pnl),
        "wins": int((pnl > 0).sum()),
        "losses": int((pnl < 0).sum()),
        "breakevens": int((pnl == 0).sum()),
        "net_profit": float(pnl.sum()),
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) else None,
        "realized_pnl_drawdown": float((np.maximum.accumulate(equity) - equity).max()),
    }
