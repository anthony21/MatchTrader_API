import json
from datetime import timedelta
from decimal import Decimal

import pytest

from matchtrader.capture.store import CaptureStore


def fill(event, execution, position, **changes):
    return event.model_copy(update={
        'schema_version': '1.1.0', 'event_id': execution, 'execution_id': execution,
        'kind': 'FILL', 'action': 'OBSERVE', 'position_id': position, 'fill_effect': 'OPEN',
        'quantity': Decimal('.4'), 'cumulative_filled_quantity': Decimal('.4'),
        'remaining_quantity': Decimal('.6'), **changes,
    })


def test_partial_split_duplicate_fill_and_restart(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    first = fill(event, 'execution1', 'position1')
    store.record(first)
    store.record(first.model_copy(update={'event_id': 'redelivery'}))
    store.record(fill(event, 'execution2', 'position2', quantity=Decimal('.3')))
    snapshot = store.mapping_view('demo')[0]
    assert len(snapshot['fills']) == 2
    assert snapshot['quantities'][0]['open_filled'] == '0.7'
    assert snapshot['quantities'][0]['partial']
    assert store.trade(identity)['source_quantity'] == '1'
    assert store.trade(identity)['source_position_id'] == ''
    with pytest.raises(ValueError, match='Split'):
        store.mappings.guard_position(identity)
    with pytest.raises(ValueError, match='conflicting'):
        store.record(first.model_copy(update={'event_id': 'bad', 'quantity': Decimal('.9')}))
    assert len(store.mapping_view('demo')[0]['fills']) == 2
    store.close()
    store = CaptureStore(tmp_path)
    assert store.record(first)[1]
    assert len(store.mapping_view('demo')[0]['fills']) == 2
    store.close()


def test_merged_position_and_account_scoped_executions(tmp_path, event):
    store = CaptureStore(tmp_path)
    first, _ = store.record(event)
    store.record(fill(event, 'f1', 'merged'))
    other = event.model_copy(update={'event_id': 'order2', 'order_id': 'order2'})
    second, _ = store.record(other)
    store.record(fill(other, 'f2', 'merged'))
    third = event.model_copy(update={'event_id': 'other-account', 'account_id': 'other'})
    store.record(third)
    store.record(fill(third, 'f1', 'merged', event_id='other-account-fill'))
    with pytest.raises(ValueError, match='Merged'):
        store.mappings.guard_position(first['trade_id'])
    assert set(store.mappings.owners('source', json.dumps(event.scope), 'merged')) == {
        first['trade_id'], second['trade_id']}
    close, _ = store.record(event.model_copy(update={'event_id': 'ambiguous', 'order_id': '',
                                                    'position_id': 'merged', 'action': 'CLOSE'}))
    assert close['trade_id'] is None
    store.close()


def test_destination_scope_and_no_invented_fills(tmp_path, event):
    store = CaptureStore(tmp_path, broker='https://aqua.example')
    row, _ = store.record(event)
    store.update(row['trade_id'], destination='demo', broker_order_id='order-broker', lots='.01', state='pending')
    snapshot = store.mapping_view('demo')[0]
    assert snapshot['mapping_status'] == 'confirmed'
    assert not snapshot['fills']
    assert snapshot['quantities'][1]['cumulative'] is None
    assert store.mapping_view('other') == []
    store.close()
    with pytest.raises(ValueError, match='another broker'):
        CaptureStore(tmp_path, broker='https://other.example')


def test_legacy_journal_migration_preserves_ids_but_removes_position_as_order_guess(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    with store.db:
        store.db.execute("UPDATE trades SET destination='demo',broker_order_id='p1',broker_position_id='p1' "
                         "WHERE trade_id=?", (identity,))
        store.db.execute('DELETE FROM mapping_meta')
        store.db.execute('DELETE FROM identity_links')
    store.close()
    store = CaptureStore(tmp_path)
    assert store.trade(identity)['broker_order_id'] == ''
    assert store.trade(identity)['broker_position_id'] == 'p1'
    assert store.trade(identity)['state'] == 'uncertain'
    assert store.mappings.ids(identity, 'source', 'order') == ['order1']
    assert store.mappings.ids(identity, 'destination', 'order') == []
    assert store.record(event)[1]
    store.close()


def test_position_snapshot_is_distinct_from_contribution_and_older_totals_do_not_replace_new(tmp_path, event):
    store = CaptureStore(tmp_path)
    store.record(event)
    store.record(fill(event, 'f1', 'p1', position_quantity=Decimal('3')))
    store.record(fill(event, 'old', 'p1', execution_id='', emitted_at=event.emitted_at - timedelta(seconds=2),
                      remaining_quantity=Decimal('1')))
    snapshot = store.mapping_view('demo')[0]
    position = next(link for link in snapshot['links'] if link['kind'] == 'position')
    assert position['position_snapshot']['volume'] == '3'
    assert position['observed_open_contribution'] == '0.4'
    assert not position['allocation_confirmed']
    assert snapshot['quantities'][0]['remaining'] == '0.6'
    store.close()


def test_unknown_journal_version_cannot_be_silently_opened(tmp_path):
    store = CaptureStore(tmp_path)
    with store.db:
        store.db.execute("UPDATE mapping_meta SET value='2.0.0' WHERE key='schema_version'")
    store.close()
    with pytest.raises(ValueError, match='Unsupported mapping journal'):
        CaptureStore(tmp_path)


def test_mapping_summary_includes_human_trade_context_without_changing_identity(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    summary = store.mapping_view('demo')[0]
    assert summary['trade_id'] == row['trade_id']
    assert (summary['symbol'], summary['side'], summary['source']) == ('EURUSD', 'BUY', 'MANUAL')
    store.close()
