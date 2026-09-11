import json
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest

from matchtrader.capture.store import CaptureStore

LEGACY_TABLES = ('destination_observations', 'outcome_reasons', 'paper_sends', 'pamm_publications')


def rewind_to_1_0_0(store):
    """Give the journal a true 1.0.0 shape: drop the four tables 1.1.0 added, then
    rewind the version string. A real 1.0.0 journal never had these tables at all."""
    with store.db:
        for table in LEGACY_TABLES:
            store.db.execute(f"DROP TABLE {table}")
        store.db.execute("UPDATE mapping_meta SET value='1.0.0' WHERE key='schema_version'")


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


def test_evidence_tables_exist_for_a_single_schema_bump(tmp_path):
    store = CaptureStore(tmp_path)
    tables = {r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'destination_observations', 'outcome_reasons', 'paper_sends', 'pamm_publications'} <= tables
    store.close()


def test_observe_destination_is_monotonic_and_first_seen_at_is_immutable(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    scope = store.mappings.destination_scope('demo')

    def observed():
        return dict(store.db.execute(
            "SELECT * FROM destination_observations WHERE trade_id=? AND scope=? AND position_id='p1'",
            (identity, scope),
        ).fetchone())

    with store.db:
        store.mappings.observe_destination(
            identity, scope, 'p1', 'open_positions', order_id='o1', symbol='EURUSD', side='BUY',
            volume=Decimal('.01'), open_price=Decimal('1.15'), open_time='2024-01-01T00:00:00Z',
            open_time_millis=None, close_time=None, close_reason=None, at='2024-01-01T00:00:01+00:00',
        )
    first_seen = observed()['first_seen_at']
    assert first_seen == '2024-01-01T00:00:01+00:00'
    # An older observation must not overwrite the newer volume.
    with store.db:
        store.mappings.observe_destination(
            identity, scope, 'p1', 'open_positions', order_id='o1', symbol='EURUSD', side='BUY',
            volume=Decimal('.99'), open_price=Decimal('1.15'), open_time='2024-01-01T00:00:00Z',
            open_time_millis=None, close_time=None, close_reason=None, at='2024-01-01T00:00:00+00:00',
        )
    assert observed()['volume'] == '0.01'
    # A newer observation updates fields but never first_seen_at.
    with store.db:
        store.mappings.observe_destination(
            identity, scope, 'p1', 'open_positions', order_id='o1', symbol='EURUSD', side='BUY',
            volume=Decimal('.03'), open_price=Decimal('1.15'), open_time='2024-01-01T00:00:00Z',
            open_time_millis=None, close_time=None, close_reason=None, at='2024-01-01T00:00:02+00:00',
        )
    fresh = observed()
    assert fresh['volume'] == '0.03'
    assert fresh['first_seen_at'] == first_seen
    store.close()


def test_observe_destination_never_erases_a_previously_seen_open_time(tmp_path, event):
    # A later read-back that omits openTime (e.g. Position.openTime is optional) must not
    # null out broker time already recorded; that time is evidence and once seen stays seen.
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    scope = store.mappings.destination_scope('demo')

    def observed():
        return dict(store.db.execute(
            "SELECT * FROM destination_observations WHERE trade_id=? AND scope=? AND position_id='p1'",
            (identity, scope),
        ).fetchone())

    with store.db:
        store.mappings.observe_destination(
            identity, scope, 'p1', 'open_positions', order_id='o1', symbol='EURUSD', side='BUY',
            volume=Decimal('.01'), open_price=Decimal('1.15'), open_time='2024-01-01T00:00:00Z',
            open_time_millis=1700000000000, close_time=None, close_reason=None,
            at='2024-01-01T00:00:01+00:00',
        )
    assert observed()['open_time'] == '2024-01-01T00:00:00Z'
    assert observed()['open_time_millis'] == 1700000000000
    with store.db:
        store.mappings.observe_destination(
            identity, scope, 'p1', 'open_positions', order_id='o1', symbol='EURUSD', side='BUY',
            volume=Decimal('.02'), open_price=Decimal('1.15'), open_time=None,
            open_time_millis=None, close_time=None, close_reason=None, at='2024-01-01T00:00:02+00:00',
        )
    fresh = observed()
    assert fresh['volume'] == '0.02'
    assert fresh['open_time'] == '2024-01-01T00:00:00Z'
    assert fresh['open_time_millis'] == 1700000000000
    store.close()


def tables(store):
    return {r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_observe_destination_survives_a_local_clock_rollback_without_losing_broker_time(tmp_path, event):
    # A timeless read-back at a LATER updated_at must not permanently block a timed read-back
    # that arrives afterward with an EARLIER updated_at (e.g. after an NTP correction or a VM
    # time sync moved the local clock backwards). The guarded upsert would reject that whole
    # update; the broker time must still be filled in via the separate, unguarded statement.
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    scope = store.mappings.destination_scope('demo')

    def observed():
        return dict(store.db.execute(
            "SELECT * FROM destination_observations WHERE trade_id=? AND scope=? AND position_id='p1'",
            (identity, scope),
        ).fetchone())

    with store.db:
        store.mappings.observe_destination(
            identity, scope, 'p1', 'open_positions', order_id='o1', symbol='EURUSD', side='BUY',
            volume=Decimal('.01'), open_price=Decimal('1.15'), open_time=None,
            open_time_millis=None, close_time=None, close_reason=None, at='2024-01-01T00:00:10+00:00',
        )
    assert observed()['open_time'] is None
    assert observed()['updated_at'] == '2024-01-01T00:00:10+00:00'
    with store.db:
        store.mappings.observe_destination(
            identity, scope, 'p1', 'open_positions', order_id='o1', symbol='EURUSD', side='BUY',
            volume=Decimal('.02'), open_price=Decimal('1.15'), open_time='2024-01-01T00:00:00Z',
            open_time_millis=1700000000000, close_time=None, close_reason=None,
            at='2024-01-01T00:00:05+00:00',
        )
    fresh = observed()
    # The earlier-timestamped mutable update is rejected...
    assert fresh['volume'] == '0.01'
    assert fresh['updated_at'] == '2024-01-01T00:00:10+00:00'
    # ...but the broker time is filled in regardless, because it can only ever be filled in.
    assert fresh['open_time'] == '2024-01-01T00:00:00Z'
    assert fresh['open_time_millis'] == 1700000000000
    store.close()


def test_populated_1_0_0_journal_migrates_to_1_1_0_in_place(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    store.update(identity, destination='demo', broker_order_id='o1', broker_position_id='p1', state='open')
    trades_before = {tuple(r) for r in store.db.execute("SELECT * FROM trades")}
    links_before = {tuple(r) for r in store.db.execute("SELECT * FROM identity_links")}
    rewind_to_1_0_0(store)
    assert len(tables(store)) == 9
    store.close()

    store = CaptureStore(tmp_path)
    version = store.db.execute("SELECT value FROM mapping_meta WHERE key='schema_version'").fetchone()[0]
    assert version == '1.1.0'
    assert len(tables(store)) == 13
    assert {tuple(r) for r in store.db.execute("SELECT * FROM trades")} == trades_before
    assert {tuple(r) for r in store.db.execute("SELECT * FROM identity_links")} == links_before
    store.close()

    # Reopening an already-migrated 1.1.0 journal a second time must be idempotent.
    store = CaptureStore(tmp_path)
    version_again = store.db.execute(
        "SELECT value FROM mapping_meta WHERE key='schema_version'").fetchone()[0]
    assert version_again == '1.1.0'
    assert len(tables(store)) == 13
    assert {tuple(r) for r in store.db.execute("SELECT * FROM trades")} == trades_before
    assert {tuple(r) for r in store.db.execute("SELECT * FROM identity_links")} == links_before
    store.close()


def test_execution_key_keeps_partial_closes_of_one_position_as_separate_rows(tmp_path, event):
    # destination_observations' PK includes execution_key precisely so that multiple closing
    # executions against the same position_id/reader do not overwrite each other and their
    # volumes can be summed (defect B). open_positions rows keep the old one-row-per-position
    # behaviour because execution_key defaults to the position id when not given.
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    scope = store.mappings.destination_scope('demo')
    with store.db:
        store.mappings.observe_destination(
            identity, scope, 'p1', 'closed_positions', execution_key='close-1',
            order_id='c1', symbol='EURUSD', side='BUY', volume=Decimal('.4'), open_price=Decimal('1.15'),
            open_time='2024-01-01T00:00:00Z', open_time_millis=None, close_time='2024-01-02T00:00:00Z',
            close_reason='CLIENT', at='2024-01-02T00:00:00+00:00',
        )
        store.mappings.observe_destination(
            identity, scope, 'p1', 'closed_positions', execution_key='close-2',
            order_id='c2', symbol='EURUSD', side='BUY', volume=Decimal('.6'), open_price=Decimal('1.15'),
            open_time='2024-01-01T00:00:00Z', open_time_millis=None, close_time='2024-01-03T00:00:00Z',
            close_reason='CLIENT', at='2024-01-03T00:00:00+00:00',
        )
    rows = store.db.execute(
        "SELECT execution_key,volume FROM destination_observations WHERE trade_id=? AND position_id='p1' "
        "ORDER BY execution_key", (identity,),
    ).fetchall()
    assert [tuple(r) for r in rows] == [('close-1', '0.4'), ('close-2', '0.6')]
    store.close()


def test_1_0_0_journal_with_mismatched_broker_rolls_back_the_version_bump(tmp_path, event):
    store = CaptureStore(tmp_path, broker='https://aqua.example')
    store.record(event)
    rewind_to_1_0_0(store)
    store.close()

    with pytest.raises(ValueError, match='another broker'):
        CaptureStore(tmp_path, broker='https://other.example')

    # The version bump and the broker check run in the same transaction: a rejected
    # open must not leave the journal upgraded to 1.1.0 without the matching broker.
    raw = sqlite3.connect(tmp_path / "capture.sqlite3")
    try:
        version = raw.execute("SELECT value FROM mapping_meta WHERE key='schema_version'").fetchone()[0]
    finally:
        raw.close()
    assert version == '1.0.0'
