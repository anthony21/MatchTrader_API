"""Versioned event meanings and evidence labels, independent of UI presentation."""

from decimal import Decimal, InvalidOperation

MEANING_VERSION = "1.0.0"
KINDS = {
    "REQUEST": ("Request", "A source send attempt; acceptance and execution are not established."),
    "ACCEPTED": ("Accepted request", "Quantower accepted the request; this is not fill confirmation."),
    "REJECTED": ("Rejected request", "Quantower rejected the request."),
    "ORDER": ("Order", "A native order update or snapshot."),
    "FILL": ("Fill", "A reported execution; opening versus closing requires explicit fill effect."),
    "POSITION": ("Position", "An observed source position; observation is not a new opening event."),
    "SIGNAL": ("Signal", "Strategy intent; no broker execution is established."),
    "ACCOUNT": ("Account", "Source account inventory; no trade action."),
    "LEGACY": ("Legacy event", "Preview-only bridge event; never an executable native event."),
    "LEDGER": ("Ledger observation", "CSV observation; a touched level is not a fill."),
}
ACTIONS = {
    "CREATE": ("Create", "Request a new order or market position."),
    "EDIT": ("Modify", "Request a change to the linked order or position."),
    "CANCEL": ("Cancel", "Request cancellation of the linked pending order."),
    "CLOSE": ("Close", "Request a full or partial position close."),
    "OBSERVE": ("Observe", "Record activity without initiating a broker action."),
}
SOURCES = {"R01": "R01 strategy", "X17": "X17 strategy", "P01": "P01 manual", "MANUAL": "Manual",
           "UNKNOWN": "Unknown source"}
RESULTS = {"accepted": "Broker accepted", "captured": "Captured", "held": "Held", "uncertain": "Uncertain",
           "preview": "Preview only", "observation": "Observed"}


def label(code, catalog):
    title, description = catalog.get(code, (code or "Unknown", "Unrecognized code; retained without inference."))
    return {"code": code, "label": title, "description": description}


def meaning(event, origin=None):
    kind, action = event.get('kind', ''), event.get('action', '')
    source = origin if origin in SOURCES and origin != 'UNKNOWN' else event.get('source', 'UNKNOWN')
    source = source if source in SOURCES else 'UNKNOWN'
    opened = {"state": "unconfirmed", "label": "Not confirmed",
              "description": "No evidence in this event that a new source trade opened."}
    try:
        positive = Decimal(str(event.get('quantity', 0))) > 0
    except (InvalidOperation, TypeError):
        positive = False
    if event.get('snapshot'):
        opened = {"state": "snapshot", "label": "Snapshot", "description": "Existing inventory, not a new opening."}
    elif kind == 'FILL' and event.get('execution_id') and positive:
        effect = event.get('fill_effect', 'UNKNOWN')
        opened = {
            "state": "confirmed" if effect == 'OPEN' else "closing" if effect == 'CLOSE' else "fill_unknown",
            "label": "Opening fill" if effect == 'OPEN' else "Closing fill" if effect == 'CLOSE' else "Fill · effect unknown",
            "description": "Source execution evidence only; does not confirm an Aqua fill or that a partial close is flat.",
        }
    elif kind == 'POSITION':
        opened = {"state": "removed" if event.get('status') == 'Removed' else "observed",
                  "label": "Position removed" if event.get('status') == 'Removed' else "Position observed",
                  "description": "Position lifecycle observation; not proof that this event opened a new trade."}
    return {"version": MEANING_VERSION, "event": label(kind, KINDS), "action": label(action, ACTIONS),
            "source": {"code": source, "label": SOURCES[source],
                       "basis": "trade origin" if origin and origin != 'UNKNOWN' else "reported source"},
            "action_source": event.get('source', 'UNKNOWN'), "opened": opened,
            "result": RESULTS.get(event.get('decision'), event.get('decision') or 'Not evaluated')}


def catalog():
    return {"version": MEANING_VERSION, "events": [label(code, KINDS) for code in KINDS],
            "actions": [label(code, ACTIONS) for code in ACTIONS], "sources": SOURCES}
