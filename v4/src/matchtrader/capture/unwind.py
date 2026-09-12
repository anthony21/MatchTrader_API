"""Automatic unwinding of exposure the owner already created; nothing here ever opens anything.

The owner's rule is asymmetric. Opening is strictly manual: a captured signal is a candidate
and reaches the broker only through manual_send. Removing exposure is the opposite: when the
source strategy reports that a lifecycle was *cancelled* (a resting pending order) or *closed*
(an open position), the order or position the owner sent for that lifecycle is cancelled or
closed at once, without a click, because a cancel or close only ever removes exposure and an
order left stranded because nobody was watching is the worse outcome.

Consequences that are deliberate, and asserted by tests:

- No toggle is consulted. The per-source switch and the paper/live master switch govern
  *opening*; exposure that already exists is unwound whatever they say now.
- Only trades actually sent are touched: the linked trade must hold a confirmed broker order
  id (to cancel) or position id (to close). A paper send or an unsent candidate created nothing
  at the broker and is a no-op here - the broker session is never touched for it.
- The link is the lifecycle label the source puts on its order comment, captured by the
  Quantower extension as `source_label` on the ACCEPTED CREATE event, scoped to the sending
  machine - the same label/scope identity signal_copy uses to pair an intent with its cancel.
  A label shared by several sent trades is ambiguous and nothing is done.
- A close never guesses: the position must be returned by the broker under the exact id (or
  the exact opening order id) with the trade's symbol and side, and MappingLedger.guard_position
  refuses a split or merged position. A `closed` lifecycle whose copy never filled and is still
  a resting order cancels that order instead - the lifecycle is over and the order would
  otherwise be stranded - and says so.
- The attempt is committed (claim / attempts / action_history) before the write, exactly as
  manual_send and the router do, so an unknown outcome is left `uncertain` for reconciliation
  and is never repeated; a second delivery of the same signal is deduplicated upstream and a
  different signal for the same trade is refused by the trade's state.
- Every outcome, including every refusal, is recorded through store.record_reason with an
  honest origin: `broker` when the broker answered, `local` for our own checks, `transport`
  only when the wire failed. Nothing is recorded as a bare unknown.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from ..core.errors import WritesDisabledError
from ..core.reason import local_reason
from .manual_send import candidate_event
from .router import CaptureRouter, _unverified, record_failure

CANCEL_KINDS = frozenset({"cancelled", "cancel"})
CLOSE_KINDS = frozenset({"closed"})
UNWIND_KINDS = CANCEL_KINDS | CLOSE_KINDS


def pending_order_request(api, order_id, request):
    """The cancel request for a broker order that is still pending and matches the stored copy.

    Shared with signal_copy.prepare_cancel so both paths keep the same two checks: the linked
    order must still be resting (a filled order's position is never closed by a cancel) and the
    broker's order must match the instrument, side and type we recorded when it was created."""
    orders = [o for o in api.active_orders() if o.id == order_id]
    if len(orders) != 1:
        raise ValueError("Linked order is no longer pending; no position is closed")
    order = orders[0]
    if (order.symbol, order.side, order.type) != (request["instrument"], request["orderSide"], request.get("type")):
        raise ValueError("Broker order does not match the stored copy")
    return {"instrument": order.symbol, "id": order.id, "orderSide": order.side, "type": order.type}


def linked_trades(store, machine, label):
    """Trades whose ACCEPTED CREATE signal carries this machine and lifecycle label."""
    if not machine or not label:
        return []
    with store.lock:
        rows = store.db.execute(
            "SELECT DISTINCT trade_id FROM events WHERE trade_id IS NOT NULL "
            "AND json_extract(payload,'$.kind')='ACCEPTED' AND json_extract(payload,'$.action')='CREATE' "
            "AND json_extract(payload,'$.machine')=? AND json_extract(payload,'$.source_label')=? "
            "ORDER BY seq",
            (machine, label),
        ).fetchall()
        return [trade for trade in (store.trade(row[0]) for row in rows) if trade]


class Refusal(ValueError):
    """A local pre-check stopped the action before any broker write. `code` names the check."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def apply(store, signal, api, destination, verified):
    """Act on one cancel/closed signal against the ledger.

    Returns None when no sent trade is linked to the signal's lifecycle - the caller records
    that there was nothing to unwind. Otherwise returns the decision for the signal's own row:
    `accepted` (the broker confirmed), `uncertain` (committed, outcome not verified, never
    retried) or `held` (a local check refused; nothing was written), with the reason, the
    exact request and the broker response when there was one."""
    action = "CANCEL" if signal.kind in CANCEL_KINDS else "CLOSE"
    correlation = f"{signal.kind} signal {signal.machineId}:{signal.clientEventId} for lifecycle {signal.label!r}"
    matches = linked_trades(store, signal.machineId, signal.label)
    if not matches:
        return None
    action_key = f"{action}:signal:{signal.clientEventId}"
    if len(matches) != 1:
        ids = ", ".join(t["trade_id"] for t in matches)
        message = (f"{len(matches)} sent trades share lifecycle {signal.label!r} on {signal.machineId}: {ids}; "
                   f"the {action.lower()} is ambiguous and nothing was sent")
        for trade in matches:
            _refuse(store, trade["trade_id"], action_key, "AmbiguousLifecycle", message, correlation)
        return _outcome("held", message)
    trade = matches[0]
    trade_id = trade["trade_id"]
    try:
        kwargs, method, values, summary = _prepare(store, trade, signal, api, destination, verified, action)
    except Refusal as refusal:
        _refuse(store, trade_id, action_key, refusal.code, str(refusal), correlation)
        return _outcome("held", str(refusal), trade_id)
    except Exception as exc:
        reason = getattr(exc, 'reason', None)
        if not isinstance(reason, dict):
            reason = local_reason(exc, evidence=f'preflight failed before a broker write; {correlation}')
        store.record_reason(trade_id, action_key, 1, 'held', reason)
        store.notify_stream()
        return _outcome('held', f'Preflight failed with {type(exc).__name__}; no broker write was attempted', trade_id)
    # Commit the attempt before any network write; a crash leaves it uncertain, never retryable.
    if not store.claim(trade_id, action_key, event=SimpleNamespace(request_id=signal.clientEventId, action=action),
                       destination=destination, request=kwargs):
        message = f"Trade {trade_id} already has an attempt in flight or recorded; no second write for {correlation}"
        _refuse(store, trade_id, action_key, "AlreadyAttempted", message, correlation)
        return _outcome("held", message, trade_id)
    store.update(trade_id, last_request=signal.clientEventId, last_event_at=signal.timestampUtc.isoformat())
    response = None
    try:
        try:
            result = method(**kwargs)
        except WritesDisabledError as exc:
            # Our own client refused before the wire: nothing was sent, and that is known, not
            # uncertain. Release the trade and close the attempt as held.
            store.update(trade_id, state=trade["state"])
            store.finish(trade_id, action_key, "held")
            message = (f"Broker writes are disabled for this dashboard process (MTR_ENABLE_WRITES); the "
                       f"{action.lower()} for trade {trade_id} was not sent")
            store.record_reason(trade_id, action_key, 1, "held", {
                "origin": "local", "code": type(exc).__name__, "summary": message,
                "evidence": f"client refused the write before any network activity; {correlation}",
            })
            store.notify_stream()
            return _outcome("held", message, trade_id, kwargs)
        response = result.model_dump(mode="json")
        if result.status != "OK":
            raise _unverified("Explicit completion status required")
        try:
            store.update(trade_id, **values)
            store.finish(trade_id, action_key, "accepted")
            store.record_reason(trade_id, action_key, 1, "accepted", {
                "origin": "broker", "code": "OK", "summary": summary,
                "evidence": f"broker write response status OK; request {json.dumps(kwargs, default=str)}; "
                            f"{correlation}",
            })
        except Exception as local_exc:
            if not isinstance(getattr(local_exc, "reason", None), dict):
                local_exc.reason = local_reason(
                    local_exc, evidence="broker accepted the write; local persistence of the accepted state failed",
                )
            raise
        decision, reason = "accepted", summary
    except Exception as exc:
        decision, reason = record_failure(store, trade_id, action_key, exc)
        reason = f"{reason}: {type(exc).__name__} during {correlation}; see outcome_reasons for trade {trade_id}"
        if response is None:
            response = {"error_type": type(exc).__name__}
    store.notify_stream()
    return _outcome(decision, reason, trade_id, kwargs, response)


def _outcome(decision, reason, trade_id=None, request=None, response=None):
    return {"decision": decision, "reason": reason, "trade_id": trade_id, "request": request, "response": response}


def _refuse(store, trade_id, action_key, code, message, correlation):
    """A refusal is still evidence the owner can investigate; it never touches the trade's state."""
    store.record_reason(trade_id, action_key, 1, "held", {
        "origin": "local", "code": code, "summary": message,
        "evidence": f"local pre-check before any broker write; {correlation}",
    })
    store.notify_stream()


def _prepare(store, trade, signal, api, destination, verified, action):
    """Every local check, then the exact broker request. Raises Refusal; never writes."""
    trade_id, label = trade["trade_id"], signal.label
    verb = action.lower()
    event = candidate_event(store, trade_id)
    if event is not None and signal.symbol and event.symbol and event.symbol != signal.symbol:
        raise Refusal("LabelSymbolMismatch",
                      f"Lifecycle {label!r} matched trade {trade_id} but the signal names {signal.symbol!r} while "
                      f"the captured order is {event.symbol!r}; nothing was sent")
    if not trade["broker_order_id"] and not trade["broker_position_id"]:
        how = "sent in paper mode only" if _paper_sent(store, trade_id) else "never sent live"
        raise Refusal("LifecycleEndedBeforeSend",
                      f"Lifecycle {label!r} ended at the source but trade {trade_id} was {how} and holds no "
                      f"broker order or position id; nothing exists at the broker to {verb}")
    if trade["destination"] != destination:
        raise Refusal("OtherDestination",
                      f"Trade {trade_id} was sent to account {trade['destination']!r}, not the selected "
                      f"{destination!r}; select that account so the {verb} can act")
    if trade["state"] in {"uncertain", "dispatching"}:
        raise Refusal("TradeUncertain",
                      f"Trade {trade_id} is {trade['state']} (order {trade['broker_order_id'] or '-'}, position "
                      f"{trade['broker_position_id'] or '-'}); reconcile it before any further broker action")
    if trade["state"] == "resolved":
        raise Refusal("AlreadyResolved",
                      f"Trade {trade_id} was already resolved at {trade['resolved_at']}; nothing left to {verb}")
    if api is None or not verified:
        raise Refusal("DestinationNotConnected",
                      f"Account {destination!r} is not connected; the {verb} for trade {trade_id} (order "
                      f"{trade['broker_order_id'] or '-'}, position {trade['broker_position_id'] or '-'}) was not sent")
    if getattr(getattr(api, 'connection', None), 'account_id', None) != destination:
        raise Refusal('AccountMismatch', 'The broker connection belongs to a different account; nothing was sent')
    settings = getattr(api, "settings", None)
    if not getattr(settings, "enable_writes", True):
        raise Refusal("WritesDisabled",
                      f"Broker writes are disabled for this dashboard process (MTR_ENABLE_WRITES); the {verb} for "
                      f"trade {trade_id} was not sent")
    if action == "CANCEL":
        if not trade["broker_order_id"]:
            raise Refusal("NoBrokerOrderId",
                          f"Trade {trade_id} holds position {trade['broker_position_id']} and no pending order; a "
                          f"cancel never closes a filled position, so nothing was sent for lifecycle {label!r}")
        return _cancel(store, trade, api, label, "cancel")
    return _close(store, trade, api, destination, label)


def _paper_sent(store, trade_id):
    with store.lock:
        return bool(store.db.execute("SELECT 1 FROM paper_sends WHERE trade_id=?", (trade_id,)).fetchone())


def _stored_copy(store, trade):
    """The CREATE request as it was sent, else the trade row's own instrument/side/type."""
    with store.lock:
        row = store.db.execute(
            "SELECT request FROM action_history WHERE trade_id=? AND action_key='CREATE'", (trade["trade_id"],)
        ).fetchone()
    if row and row["request"]:
        return json.loads(row["request"])
    return {"instrument": trade["symbol"], "orderSide": trade["side"], "type": trade["order_type"]}


def _cancel(store, trade, api, label, because):
    trade_id, order_id = trade["trade_id"], trade["broker_order_id"]
    try:
        kwargs = pending_order_request(api, order_id, _stored_copy(store, trade))
    except ValueError as exc:
        code = "OrderMismatch" if "does not match" in str(exc) else "OrderNotPending"
        raise Refusal(code, f"{exc} (trade {trade_id}, broker order {order_id}, lifecycle {label!r})") from None
    # Cancelling a remaining pending quantity does not close its filled position.
    if store.mappings.ids(trade_id, "destination", "position"):
        values = {"state": "open"}
    else:
        values = {"state": "resolved", "resolved_at": datetime.now(UTC).isoformat()}
    summary = (f"Broker accepted the cancel of pending order {order_id} for trade {trade_id} on the source's "
               f"{because} of lifecycle {label!r}")
    return kwargs, api.cancel_pending_order, values, summary


def _close(store, trade, api, destination, label):
    trade_id = trade["trade_id"]
    try:
        with store.lock:
            store.mappings.guard_position(trade_id)
    except ValueError as exc:
        raise Refusal("PositionGuard", f"{exc}; trade {trade_id} (position {trade['broker_position_id'] or '-'}) "
                                       f"was not closed for lifecycle {label!r}") from None
    # Only exact broker-provided relationships; never symbol/price matching.
    positions = CaptureRouter._positions(api.open_positions())
    related = [
        p for p in positions
        if (trade["broker_position_id"] and p.id == trade["broker_position_id"])
        or (trade["broker_order_id"] and getattr(p, "orderId", None) == trade["broker_order_id"])
    ]
    related = [p for p in related if p.symbol == trade["symbol"] and p.side == trade["side"]]
    if related:
        store.observe_positions(trade_id, destination, related)
        # The read can reveal a shared position for the first time. Re-check after linking it.
        try:
            with store.lock:
                store.mappings.guard_position(trade_id)
        except ValueError as exc:
            raise Refusal('PositionGuard', f'{exc}; trade {trade_id} was not closed') from None
    if len(related) > 1:
        ids = ", ".join(p.id for p in related)
        raise Refusal("AmbiguousPosition",
                      f"Broker returned {len(related)} positions ({ids}) for trade {trade_id}; no unambiguous "
                      f"position to close for lifecycle {label!r}")
    if len(related) == 1:
        position = related[0]
        if not trade["broker_position_id"]:
            store.update(trade_id, broker_position_id=position.id)
        kwargs = {"instrument": position.symbol, "orderSide": position.side, "positionId": position.id,
                  "volume": position.volume}
        values = {"state": "resolved", "resolved_at": datetime.now(UTC).isoformat()}
        summary = (f"Broker accepted the close of position {position.id} ({position.volume} lots) for trade "
                   f"{trade_id} on the source's close of lifecycle {label!r}")
        return kwargs, api.close_position, values, summary
    if trade["broker_order_id"]:
        # The lifecycle is over but our copy never filled: the resting order is what is stranded.
        return _cancel(store, trade, api, label, "close (the copy was still a resting order)")
    raise Refusal("NothingOpen",
                  f"Broker returned no open position {trade['broker_position_id']} for trade {trade_id} "
                  f"({trade['symbol']} {trade['side']}); it may already be closed - reconcile closed history "
                  f"for lifecycle {label!r}")
