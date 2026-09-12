"""Submit fresh bridge orders once, or cancel their exact pending broker order."""
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from . import manual_send, unwind
from .event import CaptureEvent


def receive(controller, payload):
    event = CaptureEvent.model_validate(payload)
    store = controller.native_store
    result = controller.native.receive(payload, None, controller.selected)
    if result['duplicate'] or event.kind != 'ACCEPTED' or event.action not in {'CREATE', 'CANCEL'}:
        return result
    identity = result['trade_id']
    if not identity:
        return result
    try:
        live = controller.copy_controls.mode == 'live'
        if event.action == 'CANCEL':
            if not live:
                result.update(status='paper', reason='Paper: cancellation recorded; nothing sent')
            else:
                trade = store.trade(identity)
                signal_copies = controller.signal_copy.db.execute(
                    "SELECT payload FROM signals WHERE machine=? AND label=? AND kind='intent' AND destination=? AND request IS NOT NULL",
                    (event.machine, event.source_label, controller.selected)).fetchall() if event.source_label else []
                if not trade['broker_order_id'] and not trade['broker_position_id'] and signal_copies:
                    if len(signal_copies) != 1:
                        raise ValueError('More than one signal request shares this label; cancellation is ambiguous')
                    cancel = json.loads(signal_copies[0]['payload'])
                    cancel.update(kind='cancelled', timestampUtc=event.emitted_at.isoformat(),
                                  clientEventId='bridge-cancel-' + hashlib.sha256(json.dumps([event.scope, event.event_id]).encode()).hexdigest())
                    decision = controller.receive_signals([cancel])['results'][0]
                    result.update(status=decision['status'], reason=decision['reason'],
                                  request=decision['copy_request'], response=decision['copy_response'])
                    return _record(store, event, result)
                signal = SimpleNamespace(kind='cancelled', machineId=event.machine, label=event.source_label,
                                         clientEventId=event.event_id, timestampUtc=event.emitted_at, symbol=event.symbol)
                outcome = unwind.apply(store, signal, controller.api, controller.selected,
                                       controller._destination_verified(), trade_id=identity)
                result.update(status=outcome['decision'], reason=outcome['reason'], request=outcome['request'], response=outcome['response'])
        else:
            if event.source_label:
                copied = controller.signal_copy.db.execute(
                    "SELECT 1 FROM signals WHERE machine=? AND label=? AND kind='intent' AND destination=? AND request IS NOT NULL",
                    (event.machine, event.source_label, controller.selected)).fetchone()
                if copied:
                    raise ValueError('This lifecycle already has a signal request; no second order')
            route = controller.native.route
            if not route:
                raise ValueError('Save the bridge source, destination and symbol mapping first')
            mapping = route.match(event)
            if controller.selected != route.destination_account:
                raise ValueError('Select the configured destination account')
            if event.snapshot or event.emitted_at < controller.copy_mode_since or not -5 <= (datetime.now(UTC) - event.emitted_at).total_seconds() <= 30:
                raise ValueError('Old or snapshot trade; no replay')
            if live and (not controller.settings.enable_writes or not controller._destination_verified()):
                raise ValueError('Connect the destination broker account before sending live')
            lots = mapping.fixed_lots if mapping.fixed_lots is not None else event.quantity * mapping.quantity_multiplier
            if not 0 < lots <= mapping.max_lots:
                raise ValueError('Order volume is outside the saved limit')
            # The saved route selects sources; a second per-source arming switch is unnecessary.
            controls = SimpleNamespace(mode=controller.copy_controls.mode, enabled=lambda source: source in route.sources)
            outcome = manual_send.send(store, controls, identity, lots,
                                       controller.api if live else None, controller.selected, route=route)
            result.update(outcome)
    except ValueError as exc:
        result.update(status='held', reason=str(exc))
    except Exception as exc:
        result.update(status='uncertain', reason=f'Processing interrupted ({type(exc).__name__}); inspect the journal before retrying')
    return _record(store, event, result)


def _record(store, event, result):
    with store.lock:
        row = store.db.execute('SELECT seq FROM events WHERE event_key=?',
                               (json.dumps([event.machine, event.event_id]),)).fetchone()
    store.decision(row['seq'], result['status'], result['reason'])
    store.raw_log.append('out', 'broker-order', result)
    return result
