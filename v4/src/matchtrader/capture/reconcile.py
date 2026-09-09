"""Resolve terminal trades using exact destination identities and closed history."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .router import CaptureRouter


def reconcile(store, api, destination, positions):
    with store.lock:
        trades = [
            dict(r)
            for r in store.db.execute(
                "SELECT * FROM trades WHERE destination=? AND state NOT IN ('observed','resolved')",
                (destination,),
            )
        ]
    if not trades:
        return
    positions = CaptureRouter._positions(positions)
    pending = {o.id for o in api.active_orders()}
    missing = []
    for trade in trades:
        candidates = [
            p
            for p in positions
            if p.id == trade["broker_position_id"]
            or (getattr(p, "orderId", None) == trade["broker_order_id"])
        ]
        candidates = [p for p in candidates if p.symbol == trade["symbol"] and p.side == trade["side"]]
        if len(candidates) == 1:
            values = {"broker_position_id": candidates[0].id}
            # A visible position cannot tell us whether an uncertain edit succeeded.
            if trade["state"] != "uncertain":
                values["state"] = "open"
            store.update(trade["trade_id"], **values)
        elif trade["broker_order_id"] not in pending and trade["broker_position_id"]:
            missing.append(trade)
    if not missing:
        return
    now = datetime.now(UTC)
    history = api.closed_positions(**{"from": now - timedelta(days=7), "to": now})
    for trade in missing:
        matches = [
            p
            for p in history
            if p.id == trade["broker_position_id"] and p.symbol == trade["symbol"] and p.side == trade["side"]
        ]
        # A partial close alone does not resolve the trade. No price/time-only joins.
        if matches and sum((p.volume for p in matches), Decimal(0)) >= Decimal(trade["lots"]):
            store.update(trade["trade_id"], state="resolved", resolved_at=now.isoformat())
