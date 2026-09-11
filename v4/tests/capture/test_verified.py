import json
from decimal import Decimal
from types import SimpleNamespace

from matchtrader.capture.router import CaptureRouter
from matchtrader.capture.store import CaptureStore
from matchtrader.capture.verified import NO_READ_CLOSURE_REASON, classify

SCOPE = json.dumps(['', 'demo'])


def snapshot(**overrides):
    base = {
        'symbol': 'EURUSD', 'side': 'BUY', 'state': 'open', 'broker': '', 'account_id': 'demo',
        'links': [
            {'side': 'source', 'kind': 'order', 'native_id': 'o1'},
            {'side': 'destination', 'kind': 'position', 'native_id': 'p1'},
        ],
        'destination_observations': [],
        'quantities': [],
        'reasons': [],
    }
    base.update(overrides)
    return base


def observation(**overrides):
    row = {
        'position_id': 'p1', 'symbol': 'EURUSD', 'side': 'BUY', 'reader': 'open_positions',
        'open_time': None, 'open_time_millis': None, 'close_time': None, 'updated_at': '', 'scope': SCOPE,
        'volume': None,
    }
    row.update(overrides)
    return row


def destination_quantity(requested):
    return {'side': 'destination', 'requested': requested}


def test_write_response_alone_never_verifies():
    result = classify(snapshot())
    assert not result['verified']
    assert result['state'] == 'sent_unconfirmed'
    assert result['read_back'] is None


def test_read_back_without_any_open_time_is_not_verified():
    result = classify(snapshot(destination_observations=[observation()]))
    assert not result['verified']
    assert result['state'] == 'read_back_no_time'


def test_open_time_millis_alone_verifies():
    result = classify(snapshot(destination_observations=[observation(open_time_millis=1700000000000)]))
    assert result['verified']
    assert result['state'] == 'verified_open'
    # broker_open_time is always the ISO string or None; it is never fabricated from millis.
    assert result['broker_open_time'] is None
    assert result['broker_open_time_millis'] == 1700000000000


def test_open_time_alone_verifies():
    result = classify(snapshot(destination_observations=[observation(open_time='2024-01-01T00:00:00Z')]))
    assert result['verified']
    assert result['state'] == 'verified_open'
    assert result['broker_open_time'] == '2024-01-01T00:00:00Z'
    assert result['broker_open_time_millis'] is None


def test_blank_open_time_falls_back_to_millis_without_blocking_it():
    row = observation(open_time='', open_time_millis=1700000000000)
    result = classify(snapshot(destination_observations=[row]))
    assert result['verified']
    assert result['state'] == 'verified_open'
    assert result['broker_open_time'] is None
    assert result['broker_open_time_millis'] == 1700000000000


def test_blank_open_time_without_millis_is_not_verified():
    row = observation(open_time='')
    result = classify(snapshot(destination_observations=[row]))
    assert not result['verified']
    assert result['state'] == 'read_back_no_time'
    assert result['broker_open_time'] is None
    assert result['broker_open_time_millis'] is None


def test_symbol_mismatch_is_not_verified():
    row = observation(symbol='GBPUSD', open_time='2024-01-01T00:00:00Z')
    result = classify(snapshot(destination_observations=[row]))
    assert not result['verified']
    assert result['read_back'] is None


def test_side_mismatch_is_not_verified():
    row = observation(side='SELL', open_time='2024-01-01T00:00:00Z')
    result = classify(snapshot(destination_observations=[row]))
    assert not result['verified']
    assert result['read_back'] is None


def test_merged_guard_reason_prevents_verification():
    row = observation(open_time='2024-01-01T00:00:00Z')
    links = [
        {'side': 'source', 'kind': 'order', 'native_id': 'o1'},
        {'side': 'destination', 'kind': 'position', 'native_id': 'p1', 'contributors': ['t1', 't2']},
    ]
    result = classify(snapshot(links=links, destination_observations=[row]))
    assert not result['verified']
    assert result['state'] == 'guarded'


def test_split_guard_reason_prevents_verification():
    row = observation(open_time='2024-01-01T00:00:00Z')
    links = [
        {'side': 'source', 'kind': 'order', 'native_id': 'o1'},
        {'side': 'destination', 'kind': 'position', 'native_id': 'p1', 'contributors': ['t1']},
        {'side': 'destination', 'kind': 'position', 'native_id': 'p2', 'contributors': ['t1']},
    ]
    result = classify(snapshot(links=links, destination_observations=[row]))
    assert not result['verified']
    assert result['state'] == 'guarded'


def test_closed_positions_row_is_verified_closed():
    # Closure now rests on read volume vs. the destination's requested quantity, never on
    # snapshot['state'] - see the two defect-B tests below for the state-independence itself.
    row = observation(reader='closed_positions', open_time='2024-01-01T00:00:00Z',
                      close_time='2024-01-02T00:00:00Z', volume='1')
    result = classify(snapshot(state='resolved', destination_observations=[row],
                               quantities=[destination_quantity('1')]))
    assert result['verified']
    assert result['state'] == 'verified_closed'


def test_closed_positions_row_without_resolved_state_is_verified_open_not_closed():
    # reconcile() records closed-history evidence even on a partial close, but only sets
    # state='resolved' when the matched volume fully covers the trade's lots. A closed-reader
    # row alone must not be reported as fully closed - it is verified, just not yet closed.
    row = observation(reader='closed_positions', open_time='2024-01-01T00:00:00Z',
                      close_time='2024-01-02T00:00:00Z', volume='1')
    result = classify(snapshot(state='open', destination_observations=[row],
                               quantities=[destination_quantity('2')]))
    assert result['verified']
    assert result['state'] == 'verified_open'
    assert NO_READ_CLOSURE_REASON in result['reasons']


def test_missing_source_link_is_not_verified():
    row = observation(open_time='2024-01-01T00:00:00Z')
    links = [{'side': 'destination', 'kind': 'position', 'native_id': 'p1'}]
    result = classify(snapshot(links=links, destination_observations=[row]))
    assert not result['verified']
    assert result['state'] == 'unattributed'


def test_open_and_closed_rows_together_pick_closed_as_the_strongest():
    # snapshot() orders destination_observations by first_seen_at; the open row is seen first
    # but the closed row is the stronger evidence and must win regardless of row order.
    open_row = observation(reader='open_positions', open_time='2024-01-01T00:00:00Z', updated_at='t1')
    closed_row = observation(reader='closed_positions', open_time='2024-01-01T00:00:00Z',
                              close_time='2024-01-02T00:00:00Z', updated_at='t2', volume='1')
    result = classify(snapshot(state='resolved', destination_observations=[open_row, closed_row],
                               quantities=[destination_quantity('1')]))
    assert result['verified']
    assert result['state'] == 'verified_closed'
    assert result['read_back']['reader'] == 'closed_positions'


def test_timeless_open_row_then_timed_closed_row_is_verified_not_denied():
    # Position.openTime is optional and can arrive empty on the open reader; ClosedTrade.openTime
    # is required. The naive "first matching row" picked the timeless open row and wrongly denied.
    open_row = observation(reader='open_positions', open_time=None, updated_at='t1')
    closed_row = observation(reader='closed_positions', open_time='2024-01-01T00:00:00Z',
                              close_time='2024-01-02T00:00:00Z', updated_at='t2', volume='1')
    result = classify(snapshot(state='resolved', destination_observations=[open_row, closed_row],
                               quantities=[destination_quantity('1')]))
    assert result['verified']
    assert result['state'] == 'verified_closed'


def test_guarded_trade_with_destination_and_time_is_not_reported_as_candidate():
    row = observation(open_time='2024-01-01T00:00:00Z')
    links = [
        {'side': 'source', 'kind': 'order', 'native_id': 'o1'},
        {'side': 'destination', 'kind': 'position', 'native_id': 'p1', 'contributors': ['t1', 't2']},
    ]
    result = classify(snapshot(links=links, destination_observations=[row]))
    assert result['state'] == 'guarded'
    assert 'No destination position identity has been linked to this trade yet.' not in result['reasons']


def test_unattributed_trade_with_destination_and_time_is_not_reported_as_candidate():
    row = observation(open_time='2024-01-01T00:00:00Z')
    links = [{'side': 'destination', 'kind': 'position', 'native_id': 'p1'}]
    result = classify(snapshot(links=links, destination_observations=[row]))
    assert result['state'] == 'unattributed'
    assert 'No destination position identity has been linked to this trade yet.' not in result['reasons']


def test_write_response_reader_never_verifies_even_with_matching_fields_and_time():
    # A future manual dispatch path could hand a write-response row the same shape as a
    # read-back row. The reader must be checked against the read-back allowlist, not trusted.
    row = observation(reader='write_response', open_time='2024-01-01T00:00:00Z')
    result = classify(snapshot(destination_observations=[row]))
    assert not result['verified']
    assert result['read_back'] is None
    assert result['state'] != 'verified_open'
    assert result['state'] != 'verified_closed'


def test_unknown_reader_never_verifies():
    row = observation(reader='some_future_reader', open_time='2024-01-01T00:00:00Z')
    result = classify(snapshot(destination_observations=[row]))
    assert not result['verified']
    assert result['read_back'] is None


def test_mismatched_scope_never_verifies():
    # A read from a different broker/account must not verify a trade in this scope, even
    # when position id, symbol and side all happen to line up.
    other_scope = json.dumps(['', 'other-account'])
    row = observation(reader='open_positions', open_time='2024-01-01T00:00:00Z', scope=other_scope)
    result = classify(snapshot(destination_observations=[row]))
    assert not result['verified']
    assert result['read_back'] is None
    assert result['state'] == 'sent_unconfirmed'


def test_a_dispatch_response_cannot_populate_destination_observations(tmp_path, route, event, broker):
    # This is the regression test for the house rule: a write response (an accepted
    # MARKET order/position) must never itself become a destination_observations row.
    # Only observe_positions/observe_closed (independent read-backs) may write that table.
    store = CaptureStore(tmp_path)
    router = CaptureRouter(store, route)
    router.armed = router.demo_verified = True
    market = event.model_copy(update={"order_type": "MARKET"})
    result = router.receive(market.model_dump(), broker, "demo")

    assert result["status"] == "accepted"
    assert broker.calls == [("MARKET", broker.calls[0][1])]
    assert broker.calls[0][0] == "MARKET"

    trade = store.trade(result["trade_id"])
    assert trade["broker_order_id"] == "market1"
    assert trade["broker_position_id"] == "position1"

    classification = classify(store.mapping_view("demo")[0])
    assert classification["state"] == "sent_unconfirmed"
    assert classification["read_back"] is None
    assert not classification["verified"]

    count = store.db.execute("SELECT COUNT(*) FROM destination_observations").fetchone()[0]
    assert count == 0
    store.close()


# --- Defect A: blank/whitespace open_time must never verify, at every layer. ---

def test_blank_open_time_via_store_observe_positions_does_not_block_a_later_timestamp(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    blank = SimpleNamespace(id='p1', symbol='EURUSD', side='BUY', volume=Decimal('.01'),
                            openPrice=Decimal('1.15'), openTime='', openTimeMillis=None, orderId='o1')
    store.observe_positions(identity, 'demo', [blank])
    observed = store.mapping_view('demo')[0]['destination_observations'][0]
    assert observed['open_time'] is None
    # A blank string must never be treated as "an existing value" by the later COALESCE fill-in.
    timed = SimpleNamespace(id='p1', symbol='EURUSD', side='BUY', volume=Decimal('.01'),
                            openPrice=Decimal('1.15'), openTime='2024-01-01T00:00:00Z',
                            openTimeMillis=None, orderId='o1')
    store.observe_positions(identity, 'demo', [timed])
    observed = store.mapping_view('demo')[0]['destination_observations'][0]
    assert observed['open_time'] == '2024-01-01T00:00:00Z'
    store.close()


def test_whitespace_open_time_via_store_observe_positions_never_verifies(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    store.update(identity, destination='demo')
    whitespace = SimpleNamespace(id='p1', symbol='EURUSD', side='BUY', volume=Decimal('.01'),
                                 openPrice=Decimal('1.15'), openTime='   ', openTimeMillis=None, orderId='o1')
    store.observe_positions(identity, 'demo', [whitespace])
    classification = classify(store.mapping_view('demo')[0])
    assert not classification['verified']
    assert classification['state'] == 'read_back_no_time'
    assert classification['broker_open_time'] is None
    store.close()


def test_blank_open_time_via_direct_ledger_call_does_not_block_a_later_timestamp(tmp_path, event):
    # mapping.observe_destination is the ledger boundary: it must normalize a blank open_time
    # to None itself, so a direct ledger call (bypassing store._clean_broker_time) cannot plant
    # '' and have the later COALESCE treat it as an existing value forever.
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    scope = store.mappings.destination_scope('demo')

    def observed():
        return dict(store.db.execute(
            "SELECT * FROM destination_observations WHERE trade_id=? AND position_id='p1'", (identity,),
        ).fetchone())

    with store.db:
        store.mappings.observe_destination(
            identity, scope, 'p1', 'open_positions', order_id='o1', symbol='EURUSD', side='BUY',
            volume=Decimal('.01'), open_price=Decimal('1.15'), open_time='',
            open_time_millis=None, close_time=None, close_reason=None, at='2024-01-01T00:00:01+00:00',
        )
    assert observed()['open_time'] is None
    with store.db:
        store.mappings.observe_destination(
            identity, scope, 'p1', 'open_positions', order_id='o1', symbol='EURUSD', side='BUY',
            volume=Decimal('.01'), open_price=Decimal('1.15'), open_time='2024-01-01T00:00:00Z',
            open_time_millis=None, close_time=None, close_reason=None, at='2024-01-01T00:00:02+00:00',
        )
    assert observed()['open_time'] == '2024-01-01T00:00:00Z'
    store.close()


def test_whitespace_open_time_via_direct_ledger_call_never_verifies(tmp_path, event):
    store = CaptureStore(tmp_path)
    row, _ = store.record(event)
    identity = row['trade_id']
    store.update(identity, destination='demo')
    scope = store.mappings.destination_scope('demo')
    now = '2024-01-01T00:00:01+00:00'
    with store.db:
        store.mappings.link(identity, 'destination', scope, 'position', 'p1', 'test', now)
        store.mappings.observe_destination(
            identity, scope, 'p1', 'open_positions', order_id='o1', symbol='EURUSD', side='BUY',
            volume=Decimal('.01'), open_price=Decimal('1.15'), open_time='   ',
            open_time_millis=None, close_time=None, close_reason=None, at=now,
        )
    classification = classify(store.mapping_view('demo')[0])
    assert not classification['verified']
    assert classification['state'] == 'read_back_no_time'
    assert classification['broker_open_time'] is None
    store.close()


# --- Defect B: verified_closed must rest only on read volume, never on snapshot['state']. ---

def test_two_partial_closes_summing_to_full_quantity_are_verified_closed():
    first = observation(reader='closed_positions', open_time='2024-01-01T00:00:00Z',
                        close_time='2024-01-02T00:00:00Z', volume='0.4', updated_at='t1')
    second = observation(reader='closed_positions', open_time='2024-01-01T00:00:00Z',
                         close_time='2024-01-03T00:00:00Z', volume='0.6', updated_at='t2')
    result = classify(snapshot(state='resolved', destination_observations=[first, second],
                               quantities=[destination_quantity('1')]))
    assert result['verified']
    assert result['state'] == 'verified_closed'


def test_single_partial_close_is_verified_open_with_the_limitation_reason():
    row = observation(reader='closed_positions', open_time='2024-01-01T00:00:00Z',
                      close_time='2024-01-02T00:00:00Z', volume='0.4')
    result = classify(snapshot(state='open', destination_observations=[row],
                               quantities=[destination_quantity('1')]))
    assert result['verified']
    assert result['state'] == 'verified_open'
    assert NO_READ_CLOSURE_REASON in result['reasons']


def test_close_write_response_with_no_closed_reader_row_stays_verified_open():
    # state='resolved' here comes only from a successful CLOSE write response (router.py); no
    # closed-history read-back has ever been recorded. That must never report verified_closed.
    row = observation(reader='open_positions', open_time='2024-01-01T00:00:00Z')
    result = classify(snapshot(state='resolved', destination_observations=[row]))
    assert result['verified']
    assert result['state'] == 'verified_open'
    assert NO_READ_CLOSURE_REASON in result['reasons']


def test_missing_destination_requested_quantity_never_verifies_closed():
    row = observation(reader='closed_positions', open_time='2024-01-01T00:00:00Z',
                      close_time='2024-01-02T00:00:00Z', volume='1')
    result = classify(snapshot(state='resolved', destination_observations=[row], quantities=[]))
    assert result['state'] == 'verified_open'
    assert result['state'] != 'verified_closed'


def test_unparseable_destination_requested_quantity_never_verifies_closed():
    row = observation(reader='closed_positions', open_time='2024-01-01T00:00:00Z',
                      close_time='2024-01-02T00:00:00Z', volume='1')
    result = classify(snapshot(state='resolved', destination_observations=[row],
                               quantities=[destination_quantity('not-a-number')]))
    assert result['state'] == 'verified_open'
    assert result['state'] != 'verified_closed'
