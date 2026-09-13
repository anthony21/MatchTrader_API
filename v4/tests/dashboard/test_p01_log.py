import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from matchtrader.dashboard.p01_log import P01Log


def line(message):
    return f'2026-09-11T17:28:10.2120822Z {message}\n'


def test_buy_sell_removal_keep_labels_and_never_claim_execution(tmp_path):
    path = tmp_path / 'p01.log'
    path.write_text(line('old record'))
    log = P01Log(path)
    log.start()
    assert not log.poll()
    with path.open('a') as f:
        f.write(line("box OPEN clicked id='P01RR_172810_193' side=0 type=Limit entry=76702.2057320639 sl=76000 tp=78000"))
        f.write(line("box OPEN clicked id='P01RR_172810_194' side=1 type=Limit entry=80000 sl=81000 tp=79000"))
        f.write(line('signal band x P01RR_172810_193'))
        f.write(line('signal band x P01RR_172810_194'))
    assert log.poll()
    sell, buy, *_ = log.feed()
    assert sell['side'] == 'SELL' and sell['price'] == '80000'
    assert buy['side'] == 'BUY' and buy['price'] == '76702.2057320639'
    assert sell['trade_id'] != buy['trade_id']
    assert sell['action'] == buy['action'] == 'REMOVE'
    assert all(e['decision'] == 'observed' and not e['account_id'] and not e['symbol'] for e in log.feed())
    assert not log.poll()


def test_partial_lines_rotation_missing_file_and_bounded_memory(tmp_path):
    path = tmp_path / 'p01.log'
    log = P01Log(path)
    log.start()
    assert not log.poll() and log.error
    path.write_text(line("FIRE id='P01RR_1_1' armed=False")[:-1])
    assert not log.poll() and not log.feed()
    with path.open('a') as f:
        f.write('\n')
    assert log.poll() and len(log.feed()) == 1
    path.write_text(line('short'))
    assert log.poll() and log.feed()[0]['reason'] == 'short'
    path.unlink()
    path.write_text(line('replacement'))
    assert log.poll() and log.feed()[0]['reason'] == 'replacement'
    for i in range(300):
        log.record(line(f"FIRE id='P01RR_1_{i}' armed=False").strip())
    assert len(log.feed()) == len(log.labels) == 200
    log.start()
    assert not log.poll()


def test_level_origin_labels_from_the_v2_build_are_recognised_and_joined_to_state(tmp_path):
    """BTCUSD boxes carry L:<edge>@<wall>@<bar> ids; they must reach the copier like P01RR_ ones."""
    log = P01Log(tmp_path / 'P01_RR.log')
    stamp = datetime.now(UTC).isoformat()
    log.record(f"{stamp} box OPEN clicked id='L:low@0_1029@6016' side=0 type=Stop entry=77130.52 "
               "sl=77092.59 tp=77168.45 panel=absent -> signal NOW")
    log.record(f"{stamp} FIRE id='L:low@0_1029@6016' armed=False signalOnly=False")
    log.record(f"{stamp} level available again: L:low@0_1029@6016 (trade ended)")
    log.record(f"{stamp} signal band x L:low@0_1029@6016")
    removed, released, fired, intent = log.feed()
    assert intent['action'] == 'INTENT' and intent['trade_id'] == 'L:low@0_1029@6016'
    assert intent['side'] == 'BUY' and intent['order_type'] == 'Stop' and intent['price'] == '77130.52'
    assert fired['trade_id'] == released['trade_id'] == removed['trade_id'] == 'L:low@0_1029@6016'
    assert (fired['action'], released['action'], removed['action']) == ('SIGNAL', 'RELEASE', 'REMOVE')
    state = {'utc': stamp, 'action': 'open', 'label': 'L:low@0_1029@6016', 'side': 0,
             'symbol': 'BTCUSD', 'entry': 77130.52, 'sl': 77092.59, 'tp': 77168.45, 'volume': 0}
    (tmp_path / 'P01_STATE.json').write_text(json.dumps(state))
    signal = log.signal(log.drain_intents()[0])
    assert signal['label'] == 'L:low@0_1029@6016' and signal['copyOrderType'] == 'STOP'
    assert signal['symbol'] == 'BTCUSD' and signal['side'] == 'BUY'


def test_invalid_timestamp_is_not_an_event(tmp_path):
    log = P01Log(tmp_path / 'p01.log')
    log.record('not a timestamp')
    log.record('2026-09-11T12:00:00 no timezone')
    assert not log.feed()


def test_observed_close_cancel_all_is_distinct_from_per_label_release(tmp_path):
    log = P01Log(tmp_path / 'p01.log')
    log.record(line('card: Close/Cancel All').strip())
    log.record(line('level available again: P01RR_173409_194 (trade ended)').strip())
    log.record(line('level available again: P01RR_173415_195 (trade ended)').strip())
    log.record(line('card Close/Cancel All -> bands+panel+dry ok=3').strip())
    result, sell, buy, command = log.feed()
    assert command['action'] == 'CLOSE_CANCEL_INTENT' and not command['trade_id']
    assert buy['trade_id'] == 'P01RR_173409_194' and sell['trade_id'] == 'P01RR_173415_195'
    assert buy['action'] == sell['action'] == 'RELEASE'
    assert result['action'] == 'TOOL_RESULT'
    assert all(e['meaning']['opened']['state'] == 'unconfirmed' for e in log.feed())


@pytest.mark.parametrize('side,order_type,sl,tp', [(1, 'Stop', 105, 95), (0, 'Limit', 95, 105)])
def test_live_p01_route_uses_exact_state_fixed_lots_and_source_order_type(tmp_path, settings, side, order_type, sl, tp):
    import platform

    from matchtrader.dashboard.controller import DashboardController
    from tests.dashboard.test_signal_copy import Broker, config

    controller = DashboardController(settings, tmp_path / 'data', interactive_copying=True)
    log = controller.p01_log = P01Log(tmp_path / 'P01_RR.log')
    broker = Broker()
    route = config(machine_id=platform.node(), source='P01_LOG', p01_log_enabled=True,
                   destination_account=controller.selected)
    route['symbols']['US TECH 100']['order_type'] = 'SOURCE'
    controller.signal_copy.configure(route)
    from types import SimpleNamespace
    broker.connection = SimpleNamespace(account_id=controller.selected)
    controller.connection = 'connected'
    controller.api, controller.native.demo_verified = broker, False
    controller.running = True   # capture on: the P01 path arms from saved settings, like relay signals
    from matchtrader.dashboard.copy_controls import CopyControls
    controller.copy_controls = CopyControls(mode='live')
    stamp = datetime.now(UTC).isoformat()
    raw = f"{stamp} box OPEN clicked id='P01RR_1_1' side={side} type={order_type} entry=100 sl={sl} tp={tp}"
    state = {'utc': stamp, 'action': 'open', 'label': 'P01RR_1_1', 'side': side,
             'symbol': 'US TECH 100', 'entry': 100, 'sl': sl, 'tp': tp, 'volume': 0}
    (tmp_path / 'P01_STATE.json').write_text(json.dumps(state))
    try:
        log.record(raw)
        controller._copy_p01_intents()
        assert len(broker.calls) == 1
        assert broker.calls[0]['type'] == order_type.upper() and broker.calls[0]['volume'] == Decimal('.2')
        assert log.feed()[0]['copy_result']['status'] == 'accepted'
        log.record(raw)
        controller._copy_p01_intents()
        assert len(broker.calls) == 1
        log.record(raw.replace('P01RR_1_1', 'P01RR_1_2'))
        controller._copy_p01_intents()
        assert log.feed()[0]['copy_result']['status'] == 'held' and len(broker.calls) == 1
        controller.running = False   # capture stopped disarms the path; a later intent is not copied
        log.record(raw.replace('P01RR_1_1', 'P01RR_1_3'))
        controller._copy_p01_intents()
        assert len(broker.calls) == 1
    finally:
        controller.api = None
        controller.close()


def p01_controller(tmp_path, settings, broker, mode):
    import platform

    from matchtrader.dashboard.controller import DashboardController
    from matchtrader.dashboard.copy_controls import CopyControls
    from tests.dashboard.test_signal_copy import config

    controller = DashboardController(settings, tmp_path / 'data', interactive_copying=True)
    controller.p01_log = P01Log(tmp_path / 'P01_RR.log')
    route = config(machine_id=platform.node(), source='P01_LOG', p01_log_enabled=True,
                   destination_account=controller.selected)
    route['symbols']['US TECH 100']['order_type'] = 'SOURCE'
    controller.signal_copy.configure(route)
    from types import SimpleNamespace
    broker.connection = SimpleNamespace(account_id=controller.selected)
    controller.connection = 'connected'
    controller.api, controller.native.demo_verified = broker, False
    controller.running = True
    controller.copy_controls = CopyControls(mode=mode)
    return controller


def open_box(controller, label, stamp, side=1, order_type='Limit', sl=105, tp=95):
    state = {'utc': stamp, 'action': 'open', 'label': label, 'side': side,
             'symbol': 'US TECH 100', 'entry': 100, 'sl': sl, 'tp': tp, 'volume': 0}
    (controller.p01_log.path.parent / 'P01_STATE.json').write_text(json.dumps(state))
    controller.p01_log.record(f"{stamp} box OPEN clicked id='{label}' side={side} type={order_type} entry=100 sl={sl} tp={tp}")
    controller._copy_p01_intents()


def test_p01_release_cancels_the_live_copy_once_and_ignores_labels_never_sent(tmp_path, settings):
    from tests.dashboard.test_signal_copy import PendingBroker

    broker = PendingBroker()
    controller = p01_controller(tmp_path, settings, broker, 'live')
    log = controller.p01_log
    try:
        stamp = datetime.now(UTC).isoformat()
        open_box(controller, 'P01RR_1_1', stamp)
        assert len(broker.calls) == 1 and broker.pending[0].id == 'order-1'
        log.record(f"{stamp} level available again: P01RR_1_1 (trade ended)")
        log.record(f"{stamp} signal band x P01RR_1_1")
        controller._unwind_p01_releases()
        assert broker.cancellations == [{'instrument': 'NAS100', 'id': 'order-1', 'orderSide': 'SELL', 'type': 'LIMIT'}]
        assert broker.pending == []
        release = next(e for e in log.feed() if e['action'] == 'RELEASE')
        assert release['copy_result']['status'] == 'accepted'
        # A second release for the same label is refused, never re-sent.
        log.record(f"{stamp} level available again: P01RR_1_1 (trade ended)")
        controller._unwind_p01_releases()
        assert len(broker.cancellations) == 1
        # A release for a label that was never copied touches nothing.
        log.record(f"{stamp} level available again: P01RR_9_9 (trade ended)")
        controller._unwind_p01_releases()
        assert len(broker.cancellations) == 1
    finally:
        controller.api = None
        controller.close()


def test_close_cancel_all_card_cancels_every_open_live_copy(tmp_path, settings):
    from tests.dashboard.test_signal_copy import PendingBroker

    broker = PendingBroker()
    controller = p01_controller(tmp_path, settings, broker, 'live')
    log = controller.p01_log
    try:
        stamp = datetime.now(UTC).isoformat()
        open_box(controller, 'P01RR_2_1', stamp)
        open_box(controller, 'P01RR_2_2', stamp, side=0, sl=95, tp=105)
        assert [o.id for o in broker.pending] == ['order-1', 'order-2']
        log.record(f"{stamp} card: Close/Cancel All")
        controller._unwind_p01_releases()
        assert sorted(c['id'] for c in broker.cancellations) == ['order-1', 'order-2'] and broker.pending == []
        card = next(e for e in log.feed() if e['action'] == 'CLOSE_CANCEL_INTENT')
        assert card['copy_result']['status'] == 'multiple' and 'P01RR_2_1: accepted' in card['copy_result']['reason']
    finally:
        controller.api = None
        controller.close()


def test_a_live_copy_is_still_cancelled_after_the_master_switch_returns_to_paper(tmp_path, settings):
    from matchtrader.dashboard.copy_controls import CopyControls
    from tests.dashboard.test_signal_copy import PendingBroker

    broker = PendingBroker()
    controller = p01_controller(tmp_path, settings, broker, 'live')
    log = controller.p01_log
    try:
        stamp = datetime.now(UTC).isoformat()
        open_box(controller, 'P01RR_3_1', stamp)
        assert len(broker.pending) == 1
        controller.copy_controls = CopyControls(mode='paper')
        log.record(f"{stamp} level available again: P01RR_3_1 (trade ended)")
        controller._unwind_p01_releases()
        assert len(broker.cancellations) == 1 and broker.pending == []
        # But a paper-only copy has nothing at the broker: a release is a no-op.
        open_box(controller, 'P01RR_3_2', stamp)
        assert len(broker.calls) == 1
        log.record(f"{stamp} level available again: P01RR_3_2 (trade ended)")
        controller._unwind_p01_releases()
        assert len(broker.cancellations) == 1
    finally:
        controller.api = None
        controller.close()


def test_p01_log_copy_follows_the_shared_paper_switch_and_never_touches_the_broker_in_paper(tmp_path, settings):
    import platform

    from matchtrader.dashboard.controller import DashboardController
    from matchtrader.dashboard.copy_controls import CopyControls
    from tests.dashboard.test_signal_copy import Broker, config

    controller = DashboardController(settings, tmp_path / 'data', interactive_copying=True)
    log = controller.p01_log = P01Log(tmp_path / 'P01_RR.log')
    broker = Broker()
    route = config(machine_id=platform.node(), source='P01_LOG', p01_log_enabled=True,
                   destination_account=controller.selected)
    route['symbols']['US TECH 100']['order_type'] = 'SOURCE'
    controller.signal_copy.configure(route)
    from types import SimpleNamespace
    broker.connection = SimpleNamespace(account_id=controller.selected)
    controller.connection = 'connected'
    controller.api, controller.native.demo_verified = broker, False
    controller.running = True
    controller.copy_controls = CopyControls(mode='paper')   # the master switch, as after every restart
    stamp = datetime.now(UTC).isoformat()
    state = {'utc': stamp, 'action': 'open', 'label': 'P01RR_9_9', 'side': 1,
             'symbol': 'US TECH 100', 'entry': 100, 'sl': 105, 'tp': 95, 'volume': 0}
    (tmp_path / 'P01_STATE.json').write_text(json.dumps(state))
    try:
        log.record(f"{stamp} box OPEN clicked id='P01RR_9_9' side=1 type=Limit entry=100 sl=105 tp=95")
        controller._copy_p01_intents()
        assert broker.calls == []
        result = log.feed()[0]['copy_result']
        assert result['status'] == 'paper' and result['copy_request']['type'] == 'LIMIT'
    finally:
        controller.api = None
        controller.close()


@pytest.mark.parametrize('change', [{'label': 'other'}, {'symbol': ''}, {'side': 0}, {'entry': 101},
                                  {'sl': 106}, {'tp': 96}, {'action': 'cancel'}, {'utc': '2000-01-01T00:00:00Z'}])
def test_state_mismatch_never_produces_executable_signal(tmp_path, change):
    log = P01Log(tmp_path / 'P01_RR.log')
    stamp = datetime.now(UTC).isoformat()
    log.record(f"{stamp} box OPEN clicked id='P01RR_1_1' side=1 type=Stop entry=100 sl=105 tp=95")
    state = {'utc': stamp, 'action': 'open', 'label': 'P01RR_1_1', 'side': 1,
             'symbol': 'US TECH 100', 'entry': 100, 'sl': 105, 'tp': 95, **change}
    (tmp_path / 'P01_STATE.json').write_text(json.dumps(state))
    with pytest.raises(ValueError):
        log.signal(log.feed()[0])
