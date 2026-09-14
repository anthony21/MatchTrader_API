"""The R01 lane: ledger rows become episodes, episodes become signals, signals go through the engine."""
import platform
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from matchtrader.dashboard.controller import DashboardController
from matchtrader.dashboard.copy_controls import CopyControls
from tests.dashboard.test_signal_copy import PendingBroker


def r01_controller(tmp_path, settings, broker, mode, **lane):
    controller = DashboardController(settings, tmp_path / 'data', interactive_copying=True)
    controller.signal_copy.configure_symbols({'BTCUSD': {'destination': 'NAS100', 'lots': '0.2', 'order_type': 'SOURCE'}})
    controller.configure_r01({'machine_id': platform.node(), 'destination_account': controller.selected,
                              'exclusive_destination': True, **lane})
    broker.connection = SimpleNamespace(account_id=controller.selected)
    controller.connection = 'connected'
    controller.api, controller.native.demo_verified = broker, False
    controller.running = True
    controller.copy_controls = CopyControls(mode=mode)
    return controller


def row(kind, label, side='short', entry='77200', sl='77240', tp='77120', grade='PRIME',
        detail='resting limit at range edge', utc=None):
    return {'utc': utc or datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%S.%f0Z'), 'kind': kind, 'label': label,
            'symbol': 'BTCUSD', 'side': side, 'entry': entry, 'sl': sl, 'tp': tp, 'grade': grade, 'stamp': '88.5',
            'word': grade, 'tier': '', 'cell': '', 'rfx': 'S15+', 'boxId': '', 'armed': '1', 'detail': detail}


def test_seven_digit_r01_timestamps_are_accepted():
    assert DashboardController._r01_timestamp('2026-09-13T19:01:10.7947099Z') == '2026-09-13T19:01:10.794709Z'
    assert DashboardController._r01_timestamp('2026-09-13T19:01:10Z') == '2026-09-13T19:01:10Z'


def test_an_intent_is_decided_and_recorded_as_paper_with_the_exact_request(tmp_path, settings):
    controller = r01_controller(tmp_path, settings, PendingBroker(), 'paper')
    try:
        result = controller._copy_r01_row(row('intent', 'R01_BTCUSD_short_0_1_0_2'), ['r5:b8|PRIME|'])
        assert result['status'] == 'paper' and result['copy_request']['type'] == 'LIMIT'
        assert result['copy_request']['instrument'] == 'NAS100' and result['copy_request']['volume'] == '0.2'
        assert result['label'] == 'R01_BTCUSD_short_0_1_0_2#' + row('intent', 'x')['utc'][:16] + result['label'].split('#')[1][16:]
        assert controller.api.calls == []
        feed = controller.r01_copy.feed()['events']
        assert feed[0]['source'] == 'R01' and feed[0]['status'] == 'paper'
    finally:
        controller.api = None
        controller.close()


def test_duplicate_intents_from_other_instances_and_touches_never_create_a_second_signal(tmp_path, settings):
    controller = r01_controller(tmp_path, settings, PendingBroker(), 'paper')
    try:
        first = controller._copy_r01_row(row('intent', 'L'), [])
        again = controller._copy_r01_row(row('intent', 'L'), [])
        assert first['status'] == 'paper' and again['status'] == 'duplicate'
        assert controller._copy_r01_row(row('touched', 'L'), []) is None
        assert len(controller.r01_copy.feed()['events']) == 1
    finally:
        controller.api = None
        controller.close()


def test_live_intent_places_the_order_and_the_ledger_cancel_row_cancels_it(tmp_path, settings):
    broker = PendingBroker()
    controller = r01_controller(tmp_path, settings, broker, 'live')
    try:
        result = controller._copy_r01_row(row('intent', 'R01_BTCUSD_short_0_5_0_9', entry='100', sl='105', tp='95'), [])
        assert result['status'] == 'accepted' and broker.pending[0].id == 'order-1'
        assert broker.calls[0] == {'instrument': 'NAS100', 'orderSide': 'SELL', 'volume': Decimal('0.2'),
                                   'slPrice': Decimal('105'), 'tpPrice': Decimal('95'), 'type': 'LIMIT', 'price': Decimal('100')}
        result = controller._copy_r01_row(row('cancelled', 'R01_BTCUSD_short_0_5_0_9', entry='100', sl='105', tp='95',
                                              detail='range id no longer live, side untouched'), [])
        assert result['status'] == 'accepted' and broker.pending == [] and len(broker.cancellations) == 1
        # The label is free again: a fresh intent opens a new episode and a new order.
        result = controller._copy_r01_row(row('intent', 'R01_BTCUSD_short_0_5_0_9', entry='100', sl='105', tp='95'), [])
        assert result['status'] == 'accepted' and len(broker.calls) == 2
    finally:
        controller.api = None
        controller.close()


def test_a_re_priced_intent_cancels_the_old_episode_before_opening_the_new_one(tmp_path, settings):
    broker = PendingBroker()
    controller = r01_controller(tmp_path, settings, broker, 'live')
    try:
        controller._copy_r01_row(row('intent', 'L', entry='100', sl='105', tp='95'), [])
        result = controller._copy_r01_row(row('intent', 'L', entry='100.5', sl='105', tp='95'), [])
        assert 'cancelled accepted' in result['reason'] and 'intent accepted' in result['reason']
        assert len(broker.cancellations) == 1 and [o.id for o in broker.pending] == ['order-2']
    finally:
        controller.api = None
        controller.close()


def test_grades_gate_intents_and_a_downgrade_retracts_a_resting_copy(tmp_path, settings):
    broker = PendingBroker()
    controller = r01_controller(tmp_path, settings, broker, 'live', accepted_grades=['PRIME', 'STRONG'])
    try:
        held = controller._copy_r01_row(row('intent', 'W', grade='WEAK', entry='100', sl='105', tp='95'), [])
        assert held['status'] == 'held' and 'Grade WEAK' in held['reason'] and broker.calls == []
        controller._copy_r01_row(row('intent', 'P', grade='PRIME', entry='100', sl='105', tp='95'), [])
        assert len(broker.pending) == 1
        observed = controller._copy_r01_row(row('regrade', 'P', grade='STRONG', entry='100', sl='105', tp='95'), [])
        assert observed['status'] == 'observed' and len(broker.pending) == 1
        retracted = controller._copy_r01_row(row('regrade', 'P', grade='FAIR', entry='100', sl='105', tp='95'), [])
        assert retracted['status'] == 'accepted' and broker.pending == [] and len(broker.cancellations) == 1
    finally:
        controller.api = None
        controller.close()


def test_the_r01_lane_has_its_own_settings_and_refuses_other_sources(tmp_path, settings):
    controller = DashboardController(settings, tmp_path / 'data', interactive_copying=True)
    try:
        assert controller.r01_copy.config is None and controller.r01_copy.path != controller.signal_copy.path
        with pytest.raises(ValueError, match='source must be R01'):
            controller.configure_r01({'machine_id': 'qt', 'source': 'chain', 'destination_account': controller.selected,
                                      'exclusive_destination': True})
        with pytest.raises(ValueError, match='no P01'):
            controller.configure_r01({'machine_id': 'qt', 'destination_account': controller.selected,
                                      'exclusive_destination': True, 'p01_log_enabled': True})
        with pytest.raises(ValueError, match='symbol mapping'):
            controller.configure_r01({'machine_id': 'qt', 'destination_account': controller.selected,
                                      'exclusive_destination': True})
        controller.signal_copy.configure_symbols({'BTCUSD': {'destination': 'BTCUSD', 'lots': '0.01', 'order_type': 'SOURCE'}})
        saved = controller.configure_r01({'machine_id': 'qt', 'destination_account': controller.selected,
                                          'exclusive_destination': True, 'accepted_grades': ['PRIME'], 'risk_usd': '5'})
        assert saved['config']['source'] == 'R01' and saved['config']['risk_usd'] == '5'
        assert saved['config']['symbols']['BTCUSD']['destination'] == 'BTCUSD'   # the shared map, read through this lane
        assert controller.signal_copy.config is None                              # the P01 lane is untouched
        assert controller._copy_r01_row(row('intent', 'L'), []) is None or controller.running is False
    finally:
        controller.close()
