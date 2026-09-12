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
    controller.signal_copy.arm(True)
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
        controller.signal_copy.arm(False)
        log.record(raw.replace('P01RR_1_1', 'P01RR_1_3'))
        controller._copy_p01_intents()
        assert len(broker.calls) == 1
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
