"""Version 1 native capture envelopes; broker credentials never enter this protocol."""

import json
from uuid import UUID

from .event import CaptureEvent

VERSION = '1.0.0'
SUBPROTOCOL = 'hcamm.capture.v1'
PATH = '/capture/ws'
MAX_MESSAGE = 32768
MAX_EVENT = 16384


class ProtocolFault(ValueError):
    def __init__(self, code, event_id=None):
        self.code, self.event_id = code, event_id
        super().__init__(code)


def nack(code, event_id=None):
    result = {'type': 'nack', 'transport_version': VERSION, 'code': code,
              'retryable': code in {'capture_stopped', 'busy', 'sender_busy'}}
    if event_id:
        result['event_id'] = event_id
    return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Repeated JSON key')
        result[key] = value
    return result


def decode(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_MESSAGE:
        raise ProtocolFault('invalid_event')
    try:
        value = json.loads(raw, object_pairs_hook=_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError):
        raise ProtocolFault('invalid_event') from None
    if not isinstance(value, dict):
        raise ProtocolFault('invalid_event')
    event = value.get('event')
    identity = event.get('event_id') if isinstance(event, dict) else None
    identity = identity if isinstance(identity, str) and 0 < len(identity) <= 200 else None
    if value.get('transport_version') != VERSION:
        raise ProtocolFault('unsupported_version', identity)
    return value


def hello(value):
    if set(value) != {'type', 'transport_version', 'event_schema_version', 'machine', 'sender_instance_id'} or value['type'] != 'hello':
        raise ProtocolFault('invalid_event')
    if value['event_schema_version'] != '1.1.0':
        raise ProtocolFault('unsupported_version')
    machine = value['machine']
    if not isinstance(machine, str) or not 1 <= len(machine) <= 100:
        raise ProtocolFault('invalid_event')
    try:
        UUID(value['sender_instance_id'])
    except (ValueError, TypeError, AttributeError):
        raise ProtocolFault('invalid_event') from None
    return machine


def event(value, machine):
    identity = value.get('event', {}).get('event_id') if isinstance(value.get('event'), dict) else None
    identity = identity if isinstance(identity, str) and 0 < len(identity) <= 200 else None
    if set(value) != {'type', 'transport_version', 'event'} or value['type'] != 'event':
        raise ProtocolFault('invalid_event', identity)
    try:
        raw = value['event']
        if len(json.dumps(raw, ensure_ascii=False).encode('utf-8')) > MAX_EVENT:
            raise ValueError()
        if raw.get('schema_version') != '1.1.0':
            raise ProtocolFault('unsupported_version', identity)
        parsed = CaptureEvent.model_validate(raw)
    except ProtocolFault:
        raise
    except (ValueError, TypeError, AttributeError):
        raise ProtocolFault('invalid_event', identity) from None
    if parsed.machine != machine:
        raise ProtocolFault('machine_mismatch', parsed.event_id)
    return parsed


def ack(result):
    return {'type': 'ack', 'transport_version': VERSION, 'event_id': result['event_id'],
            'durable': True, 'duplicate': result['duplicate'], 'result': result}
