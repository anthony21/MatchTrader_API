import pytest

from matchtrader.capture.meaning import ACTIONS, KINDS, catalog, meaning


def test_catalog_is_versioned_and_covers_all_contract_codes():
    from matchtrader.capture.event import CaptureEvent

    schema = CaptureEvent.model_json_schema()
    for field, known in [('kind', KINDS), ('action', ACTIONS)]:
        assert set(schema['properties'][field]['enum']) <= set(known)
    assert catalog()['version'] == '1.0.0'
    assert all(item['description'] for item in catalog()['events'] + catalog()['actions'])
    assert meaning({'kind': 'NEW_KIND', 'action': 'NEW_ACTION'})['event']['code'] == 'NEW_KIND'


@pytest.mark.parametrize(('update', 'expected'), [
    ({}, 'confirmed'), ({'fill_effect': 'CLOSE'}, 'closing'),
    ({'fill_effect': 'UNKNOWN'}, 'fill_unknown'), ({'snapshot': True}, 'snapshot'),
    ({'execution_id': ''}, 'unconfirmed'), ({'quantity': '0'}, 'unconfirmed'),
    ({'quantity': 'invalid'}, 'unconfirmed'), ({'quantity': 'NaN'}, 'unconfirmed'),
    ({'kind': 'ACCEPTED'}, 'unconfirmed'), ({'kind': 'REQUEST'}, 'unconfirmed'),
    ({'kind': 'POSITION'}, 'observed'), ({'kind': 'POSITION', 'status': 'Removed'}, 'removed'),
])
def test_opening_requires_explicit_execution_evidence(update, expected):
    event = {'kind': 'FILL', 'action': 'OBSERVE', 'execution_id': 'e1', 'quantity': '.25',
             'fill_effect': 'OPEN', 'decision': 'accepted', **update}
    assert meaning(event)['opened']['state'] == expected


def test_trade_origin_is_separate_from_action_source_and_unknown_is_not_guessed():
    mapped = meaning({'source': 'MANUAL', 'action': 'EDIT'}, origin='R01')
    assert mapped['source'] == {'code': 'R01', 'label': 'R01 strategy', 'basis': 'trade origin'}
    assert mapped['action_source'] == 'MANUAL'
    assert meaning({'source': '', 'sending_source': ''})['source']['code'] == 'UNKNOWN'
    assert meaning({'source': 'X17'})['source']['label'] == 'X17 strategy'
