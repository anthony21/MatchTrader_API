"""Read-only classification of whether a trade's destination leg is provably confirmed.

A write response (an accepted order, a created position) only proves the broker
accepted the request. It can never satisfy `verified`: that requires a later,
independent read-back - an open position or a closed-history row carrying the
broker's own native id and its own open time - matched against the snapshot's
symbol and side. This module takes a MappingLedger.snapshot() dict and returns a
plain classification; it never touches the database and never causes a write.

The evidence boundary is enforced here, not just by convention at the call sites:
only a row whose `reader` is a genuine read-back reader, and whose `scope` matches
the snapshot's own broker/account, may ever contribute to verification. A row from
any other reader (e.g. a write response someone wired into the same table) or from
a different broker/account is never counted, regardless of what fields it carries.

`verified_closed` rests only on broker READ evidence: it sums `volume` across the
qualifying closed_positions rows (one row per closing execution) and compares that
sum against the destination's requested quantity. `snapshot["state"]` is never
consulted for this determination - a trade can be `state='resolved'` purely because
a CLOSE write response succeeded (see capture/router.py), and that alone is not
read evidence of closure.

Known limitation (not fixed here): capture/reconcile.py excludes `state='resolved'`
trades from its selection, so a trade that reached `resolved` via a write response
(with no closed-history read-back yet) is never revisited for closed-history
read-back and will stay `verified_open` indefinitely, even if it did in fact close.
Widening reconcile's selection is a behaviour change outside this module's scope.
"""

import json
from decimal import Decimal, InvalidOperation

READ_BACK_READERS = frozenset({"open_positions", "closed_positions"})
CLOSED_READERS = frozenset({"closed_positions"})

NO_READ_CLOSURE_REASON = (
    "Closure is not confirmed by a broker read; the position may have closed "
    "without read-back evidence."
)


def _has_time(row):
    open_time = row.get("open_time")
    has_open_time = isinstance(open_time, str) and open_time.strip() != ""
    return has_open_time or row.get("open_time_millis") is not None


def _destination_requested(snapshot):
    for quantity in snapshot.get("quantities", []):
        if quantity.get("side") == "destination":
            requested = quantity.get("requested")
            if requested in (None, ""):
                return None
            try:
                return Decimal(str(requested))
            except (InvalidOperation, ValueError):
                return None
    return None


def _closed_volume(rows):
    total = Decimal(0)
    for row in rows:
        if row.get("reader") not in CLOSED_READERS:
            continue
        volume = row.get("volume")
        if volume in (None, ""):
            continue
        try:
            total += Decimal(str(volume))
        except (InvalidOperation, ValueError):
            continue
    return total


def classify(snapshot):
    links = snapshot["links"]
    destination_link = next(
        (link for link in links if link["side"] == "destination" and link["kind"] == "position"
         and link["native_id"]),
        None,
    )
    has_source = any(link["side"] == "source" for link in links)
    destination_positions = [link for link in links
                              if link["side"] == "destination" and link["kind"] == "position"]
    guarded = len(destination_positions) > 1 or any(
        len(link.get("contributors", [])) > 1 for link in destination_positions
    )

    expected_scope = json.dumps([snapshot["broker"], snapshot["account_id"]])
    rows = []
    if destination_link is not None:
        rows = [r for r in snapshot["destination_observations"]
                if r["position_id"] == destination_link["native_id"]
                and r["symbol"] == snapshot["symbol"] and r["side"] == snapshot["side"]
                and r.get("reader") in READ_BACK_READERS
                and r.get("scope") == expected_scope]
    # Prefer a timed row over a timeless one, then a closed reader over an open one,
    # then the most recently updated; snapshot() orders by first_seen_at so the
    # naive "first match" used to always pick the earliest-seen (usually open) row.
    row = max(
        rows,
        key=lambda r: (_has_time(r), r.get("reader") in CLOSED_READERS, r.get("updated_at") or ""),
        default=None,
    )
    has_time = _has_time(row) if row else False
    verified = bool(destination_link) and bool(row) and has_time and has_source and not guarded

    reasons = []
    if guarded:
        reasons.append("A split or merged position guard prevents attributing broker evidence to this trade.")
    if not has_source:
        reasons.append("No source identity was ever linked to this trade.")

    # Closure is decided from read volume, never from snapshot["state"]: a CLOSE write
    # response alone can set state='resolved' (capture/router.py) with no closed-history
    # read-back at all, and that must not be reportable as a confirmed closure.
    closed_rows = [r for r in rows if r.get("reader") in CLOSED_READERS]
    requested = _destination_requested(snapshot)
    fully_closed = bool(closed_rows) and requested is not None and _closed_volume(rows) >= requested
    if verified and fully_closed:
        state = "verified_closed"
        reasons.append("The broker confirmed this position closed, with an open time on record.")
    elif verified:
        state = "verified_open"
        reasons.append("The broker confirmed this open position and reported its own open time.")
        if closed_rows or snapshot["state"] == "resolved":
            reasons.append(NO_READ_CLOSURE_REASON)
    elif guarded:
        state = "guarded"
    elif not has_source:
        state = "unattributed"
    elif destination_link and row and not has_time:
        state = "read_back_no_time"
        reasons.append("The broker confirmed this position but did not report its open time.")
    elif destination_link and not row:
        state = "sent_unconfirmed"
        # sent_unconfirmed outranks uncertain: a recorded destination identity with no
        # confirming read-back yet is a more specific, more useful claim than a bare
        # "trade is in-flight" state, so it is checked first.
        reasons.append("A destination identity was recorded but no independent broker read-back confirms it.")
    elif snapshot["state"] in {"uncertain", "dispatching"}:
        state = "uncertain"
        reasons.append("The trade itself is in an uncertain or in-flight state.")
    else:
        state = "candidate"
        reasons.append("No destination position identity has been linked to this trade yet.")

    # Stable shape for consumers: broker_open_time is the ISO string or None, never fabricated
    # from millis; broker_open_time_millis is the epoch millis or None. A blank OR
    # whitespace-only string must never be returned as broker_open_time, and must never block
    # the millis value from being reported.
    raw_open_time = row.get("open_time") if row else None
    broker_open_time = raw_open_time if isinstance(raw_open_time, str) and raw_open_time.strip() else None
    broker_open_time_millis = row.get("open_time_millis") if row else None

    return {
        "state": state,
        "verified": verified,
        "reasons": reasons,
        "broker_open_time": broker_open_time,
        "broker_open_time_millis": broker_open_time_millis,
        "read_back": row,
    }
