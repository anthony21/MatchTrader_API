"""Stream sections for the verified-trade ledger, built from one mapping_view() pass.

Every value here is read from the journal or from the persisted copy controls; nothing is
derived from the clock at build time. The dashboard stream hashes each section to decide
whether to resend it, so a now-derived field would make the section resend on every
tick forever. classify() is deterministic over a snapshot, so two builds over unchanged
evidence hash identically.

A paper-sent trade is reported with state "paper_sent" and verified=False: the paper path
writes no broker evidence, so classify() would call it a candidate, but it has been
consumed and belongs on the paper page - it must never read as verified or as sendable.

A signal-driven cancel or close (capture/unwind.py) is carried in the row's `unwind` field:
the action, its outcome, when it was recorded and the reason's summary and origin. When the
broker accepted the cancel of a pending order that never became a position, the row's state
is "cancelled" so the page stops offering a send; a close never changes the classifier's
state, because only a broker read-back may say a position is closed.
"""

import json

from ..capture.pamm_publisher import is_published
from ..capture.verified import classify

SOURCE_ENDED = frozenset({"Cancelled", "Refused", "Removed"})
PAPER_SENT = "paper_sent"
CANCELLED = "cancelled"
UNWIND_ACTIONS = frozenset({"CANCEL", "CLOSE"})


def _unwind(snapshot):
    """The latest signal-driven cancel or close recorded for this trade (capture/unwind.py), or a
    refusal of one. `actions` is ordered newest first; the attempt's outcome comes from
    action_history and any refusal from outcome_reasons keyed to the same action."""
    actions = [a for a in snapshot.get("actions") or [] if a.get("action") in UNWIND_ACTIONS]
    reasons = [r for r in snapshot.get("outcome_reasons") or []
               if str(r.get("action_key", "")).split(":", 1)[0] in UNWIND_ACTIONS]
    if not actions and not reasons:
        return None
    if actions:
        latest = actions[0]
        reason = next((r for r in reversed(reasons) if r.get("action_key") == latest.get("action_key")), None)
        return {"action": latest["action"], "outcome": latest.get("outcome"), "at": latest.get("updated_at"),
                "request_id": latest.get("request_id"), "request": latest.get("request"),
                "summary": reason.get("summary") if reason else None,
                "origin": reason.get("origin") if reason else None}
    refusal = reasons[-1]
    return {"action": refusal["action_key"].split(":", 1)[0], "outcome": refusal.get("outcome"),
            "at": refusal.get("at"), "request_id": refusal["action_key"].split(":")[-1], "request": None,
            "summary": refusal.get("summary"), "origin": refusal.get("origin")}


def _ids(links, side, kind):
    return [link["native_id"] for link in links if link["side"] == side and link["kind"] == kind
            and link["native_id"]]


def _cancellation(snapshot):
    reasons = snapshot.get("outcome_reasons") or []
    if reasons:
        latest = reasons[-1]
        return {key: latest.get(key) for key in ("origin", "outcome", "code", "summary", "evidence", "at")}
    if snapshot.get("source_state") in SOURCE_ENDED and not _ids(snapshot["links"], "destination", "position"):
        return {"origin": "source", "outcome": "cancelled", "code": snapshot["source_state"],
                "summary": "Source order ended before any send; not a candidate",
                "evidence": "native ORDER/POSITION event", "at": snapshot.get("updated_at")}
    return None


def verified_row(snapshot, controls, publication, paper_sent=False):
    verdict = classify(snapshot)
    links = snapshot["links"]
    read_back = verdict["read_back"]
    create = next((a for a in snapshot.get("actions", []) if a.get("action_key") == "CREATE"), None)
    reasons = list(verdict["reasons"])
    reasons += [r for r in snapshot.get("reasons", []) if r not in reasons]
    state, verified = verdict["state"], verdict["verified"]
    if paper_sent and not verified:
        state = PAPER_SENT
        reasons.insert(0, "Sent in paper mode: the exact request was recorded and nothing reached the broker.")
    unwound = _unwind(snapshot)
    if (unwound and unwound["action"] == "CANCEL" and unwound["outcome"] == "accepted"
            and snapshot.get("state") == "resolved" and not _ids(links, "destination", "position")):
        # The broker confirmed the cancel of the pending order and no position ever existed: this
        # row is cancelled, not a candidate, and must not offer a send.
        state = CANCELLED
        reasons.insert(0, "The broker accepted the cancel of this pending order on the source's signal; "
                          "no position was opened.")
    return {
        "trade_id": snapshot["trade_id"],
        "state": state,
        "verified": verified,
        "symbol": snapshot.get("symbol", ""),
        "side": snapshot.get("side", ""),
        "lots": snapshot.get("lots") or snapshot.get("source_quantity") or "",
        "source_enabled": controls.enabled(snapshot.get("source", "UNKNOWN")),
        "source": {"code": snapshot.get("source", "UNKNOWN"), "scope": snapshot.get("source_scope"),
                   "order_ids": _ids(links, "source", "order"),
                   "position_ids": _ids(links, "source", "position")},
        "destination": {"broker": snapshot.get("broker", ""), "account_id": snapshot.get("account_id", ""),
                        "order_ids": _ids(links, "destination", "order"),
                        "position_ids": _ids(links, "destination", "position")},
        "timestamps": {"sent_at": create.get("updated_at") if create else None,
                       "confirmed_at": read_back.get("first_seen_at") if read_back else None,
                       "broker_open": verdict["broker_open_time"],
                       "broker_open_millis": verdict["broker_open_time_millis"]},
        "read_back": ({"reader": read_back.get("reader"), "volume": read_back.get("volume"),
                       "open_price": read_back.get("open_price")} if read_back else None),
        "pamm": ({"published": is_published(publication), "published_at": publication.get("published_at"),
                  "upstream_status": publication.get("upstream_status")} if publication else None),
        "cancellation": _cancellation(snapshot),
        "unwind": unwound,
        "mapping_status": snapshot.get("mapping_status"),
        "reasons": reasons,
    }


def paper_sent_ids(store, trade_ids):
    ids = [i for i in dict.fromkeys(trade_ids) if i]
    if not ids:
        return set()
    marks = ",".join("?" * len(ids))
    with store.lock:
        rows = store.db.execute(
            f"SELECT DISTINCT trade_id FROM paper_sends WHERE trade_id IN ({marks})", ids,
        ).fetchall()
    return {row[0] for row in rows}


def verified_trades(snapshots, controls, publications, paper_ids, account_id):
    rows = [verified_row(snapshot, controls, publications.get(snapshot["trade_id"]),
                         snapshot["trade_id"] in paper_ids) for snapshot in snapshots]
    return {"account_id": account_id, "rows": rows}


def paper_sends(store, account_id):
    with store.lock:
        rows = store.db.execute(
            "SELECT * FROM paper_sends WHERE destination=? ORDER BY decided_at DESC LIMIT 200", (account_id,),
        ).fetchall()
    result = []
    for row in rows:
        request = json.loads(row["request"]) if row["request"] else {}
        result.append({"trade_id": row["trade_id"], "source": row["source"],
                       "symbol": request.get("instrument", ""), "side": request.get("orderSide", ""),
                       "lots": row["lots"], "request": request, "verdict": row["verdict"],
                       "reason": row["reason"], "decided_at": row["decided_at"]})
    return {"account_id": account_id, "rows": result}
