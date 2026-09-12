"""Shared one-time order submission for automatic bridge dispatch and legacy Send clients.

Paper records the formatted request without touching the broker. Live commits the
attempt before posting and retains uncertain results without retry. Symbol, side,
order type and prices come from the captured event; the caller supplies the lots.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from ..core.reason import local_reason
from .event import CaptureEvent
from .router import CaptureRouter, _unverified, record_failure
from .verified import classify

SEND_ORDER_TYPES = frozenset({"MARKET", "LIMIT", "STOP"})
PAPER_VERDICT = "would_send"
PAPER_REASON = "Paper mode: exact broker request recorded; nothing was sent"
ALREADY_SENT = "This trade was already sent once; it will not be sent again"


def candidate_event(store, trade_id):
    """The ACCEPTED CREATE signal that made this trade a candidate, or None."""
    with store.lock:
        row = store.db.execute(
            "SELECT payload FROM events WHERE trade_id=? AND json_extract(payload,'$.kind')='ACCEPTED' "
            "AND json_extract(payload,'$.action')='CREATE' ORDER BY seq DESC LIMIT 1",
            (trade_id,),
        ).fetchone()
    return CaptureEvent.model_validate_json(row[0]) if row else None


def already_sent(store, trade_id):
    with store.lock:
        paper = store.db.execute("SELECT 1 FROM paper_sends WHERE trade_id=?", (trade_id,)).fetchone()
        attempt = store.db.execute("SELECT 1 FROM attempts WHERE trade_id=?", (trade_id,)).fetchone()
    return bool(paper or attempt)


def parse_volume(volume):
    """The adjusted lot size from the front end: a finite, positive decimal spelled as a string
    or number. Booleans and anything non-numeric are refused, never coerced."""
    if isinstance(volume, bool) or volume is None:
        raise ValueError("A positive volume is required")
    try:
        lots = Decimal(str(volume))
    except (InvalidOperation, ValueError):
        raise ValueError("Volume must be a decimal number") from None
    if not lots.is_finite() or lots <= 0:
        raise ValueError("Volume must be a finite positive number")
    return lots


def prepare(store, controls, trade_id, volume, destination, route=None):
    """Every local check, in both modes, before anything is written or sent."""
    trade = store.trade(trade_id)
    if not trade:
        raise ValueError("Unknown trade")
    source = trade["source"]
    if not controls.enabled(source):
        raise ValueError(f"Source {source} is not enabled for copying")
    with store.lock:
        snapshot = store.mappings.snapshot(trade)
    verdict = classify(snapshot)
    if trade["state"] != "observed" or verdict["state"] != "candidate":
        raise ValueError(f"Trade is not a candidate (state {trade['state']}, {verdict['state']})")
    if trade["broker_order_id"] or trade["broker_position_id"]:
        raise ValueError("Trade already has a destination order")
    if trade["destination"] and trade["destination"] != destination:
        raise ValueError("Trade already belongs to another destination")
    if already_sent(store, trade_id):
        raise ValueError(ALREADY_SENT)
    event = candidate_event(store, trade_id)
    if event is None:
        raise ValueError("No accepted CREATE signal is on record for this trade")
    if not event.brackets_absolute:
        raise ValueError("Offset brackets require an explicit absolute-price conversion")
    if event.order_type not in SEND_ORDER_TYPES:
        raise ValueError("Unsupported order type; stop-limit is not silently converted")
    if event.side not in {"BUY", "SELL"}:
        raise ValueError("Missing side")
    lots = parse_volume(volume)
    # The instrument comes from the signal. An explicit route may translate the symbol
    # spelling (e.g. "EUR/USD" to "EURUSD"); nothing else about the route is consulted.
    mapped = route.symbols.get(event.symbol) if route else None
    symbol = mapped.destination if mapped else event.symbol
    if not symbol:
        raise ValueError("Signal carries no instrument")
    request = {"instrument": symbol, "orderSide": event.side, "volume": lots,
               "slPrice": event.sl, "tpPrice": event.tp}
    if event.order_type != "MARKET":
        request.update(type=event.order_type, price=event.price)
    return SimpleNamespace(trade=trade, event=event, symbol=symbol, lots=lots, request=request)


def _json_safe(value):
    return json.loads(json.dumps(value, default=str))


def send(store, controls, trade_id, volume, api, destination, *, route=None):
    """Dispatch one candidate per the copy controls. Paper never touches `api`."""
    with store.lock:
        prepared = prepare(store, controls, trade_id, volume, destination, route)
        if controls.mode == "paper":
            return _paper(store, prepared, destination)
        if api is None:
            raise ValueError("Connect the destination account before sending live")
        try:
            CaptureRouter._validate_instrument(api, prepared.symbol, prepared.lots, prepared.event)
        except ValueError:
            raise
        except Exception as exc:
            # A preflight read that failed on the wire is a refusal, not a dispatch: nothing was
            # claimed, so the owner may send again once the connection is back. Name the class
            # so the refusal is investigable; never echo the upstream message.
            raise ValueError(
                f"Preflight instrument read failed ({type(exc).__name__}); no broker write attempted"
            ) from exc
        # Commit the attempt before any network write. A duplicate click or a second
        # operator lands here and is refused by the attempts primary key.
        if not store.claim(trade_id, "CREATE", event=prepared.event, destination=destination,
                           request=prepared.request):
            raise ValueError("Action already attempted; it will not be sent again")
        store.update(
            trade_id, destination=destination, symbol=prepared.symbol, side=prepared.event.side,
            lots=str(prepared.lots), order_type=prepared.event.order_type,
            last_request=prepared.event.request_id, last_event_at=prepared.event.emitted_at.isoformat(),
        )
    return _live(store, prepared, api, trade_id)


def _paper(store, prepared, destination):
    decided_at = datetime.now(UTC).isoformat()
    with store.lock, store.db:
        store.db.execute(
            "INSERT INTO paper_sends VALUES(?,?,?,?,?,?,?,?)",
            (prepared.trade["trade_id"], prepared.trade["source"], destination,
             json.dumps(prepared.request, default=str), str(prepared.lots),
             PAPER_VERDICT, PAPER_REASON, decided_at),
        )
    store.notify_stream()
    return {"trade_id": prepared.trade["trade_id"], "mode": "paper", "status": "paper",
            "verdict": PAPER_VERDICT, "reason": PAPER_REASON, "request": _json_safe(prepared.request),
            "decided_at": decided_at, "broker_order_id": "", "broker_position_id": ""}


def _live(store, prepared, api, trade_id):
    event, request = prepared.event, prepared.request
    method = api.open_position if event.order_type == "MARKET" else api.create_pending_order
    try:
        store.raw_log.append('out', 'broker-request', {'trade_id': trade_id, 'body': _json_safe(request)})
        result = method(**request)
        store.raw_log.append('in', 'broker-response', {'trade_id': trade_id, 'body': result.model_dump(mode='json')})
        if result.status and result.status != "OK":
            raise _unverified("Unrecognized broker status")
        if not result.orderId and not result.positionId:
            raise _unverified("Broker identity missing after submission")
        values = {"state": "open" if event.order_type == "MARKET" else "pending",
                  "broker_order_id": result.orderId or ""}
        if result.positionId:
            values["broker_position_id"] = result.positionId
        try:
            store.update(trade_id, **values)
            store.finish(trade_id, "CREATE", "accepted")
        except Exception as local_exc:
            if not isinstance(getattr(local_exc, "reason", None), dict):
                local_exc.reason = local_reason(
                    local_exc,
                    evidence="broker accepted the write; local persistence of the accepted state failed",
                )
            raise
        status, reason = "accepted", "Broker accepted the mapped action"
    except Exception as exc:
        status, reason = record_failure(store, trade_id, "CREATE", exc)
    store.notify_stream()
    trade = store.trade(trade_id)
    return {"trade_id": trade_id, "mode": "live", "status": status, "verdict": status, "reason": reason,
            "request": _json_safe(request), "decided_at": trade["updated_at"],
            "broker_order_id": trade["broker_order_id"], "broker_position_id": trade["broker_position_id"]}
