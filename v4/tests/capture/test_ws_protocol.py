import json
from uuid import uuid4

import pytest

from matchtrader.capture import ws_protocol as p


def test_hello_event_and_ack_round_trip(event):
    greeting = {'type': 'hello', 'transport_version': p.VERSION, 'event_schema_version': '1.1.0',
                'machine': 'qt', 'sender_instance_id': str(uuid4())}
    assert p.hello(p.decode(json.dumps(greeting))) == 'qt'
    payload = event.model_copy(update={'schema_version': '1.1.0'}).model_dump(mode='json')
    parsed = p.event(p.decode(json.dumps({'type': 'event', 'transport_version': p.VERSION, 'event': payload})), 'qt')
    assert parsed.event_id == event.event_id and str(parsed.quantity) == '1'
    result = {'event_id': event.event_id, 'duplicate': False, 'status': 'captured'}
    assert p.ack(result)['durable'] is True
    assert p.nack('busy', event.event_id)['retryable'] is True
    assert p.nack('identity_conflict')['retryable'] is False


@pytest.mark.parametrize('raw', ['[]', '{bad', '{"transport_version":"1.0.0","transport_version":"1.0.0"}',
                                 '{"transport_version":"1.0.0","n":NaN}', 'x' * 32769, b'binary'], ids=['array','json','duplicate-key','nan','oversize','binary'])
def test_invalid_packets_are_rejected(raw):
    with pytest.raises(p.ProtocolFault):
        p.decode(raw)


def test_versions_extra_fields_machine_and_payload_limit(event):
    payload = event.model_copy(update={'schema_version': '1.1.0'}).model_dump(mode='json')
    value = {'type': 'event', 'transport_version': p.VERSION, 'event': payload}
    with pytest.raises(p.ProtocolFault, match='unsupported_version'):
        p.decode('{"transport_version":"2.0.0"}')
    with pytest.raises(p.ProtocolFault, match='machine_mismatch'):
        p.event(value, 'other')
    with pytest.raises(p.ProtocolFault, match='invalid_event'):
        p.event({**value, 'extra': True}, 'qt')
    with pytest.raises(p.ProtocolFault, match='invalid_event'):
        p.event({**value, 'event': {**payload, 'extra': 'a' * 17000}}, 'qt')
