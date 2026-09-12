"""Bridge arrivals submit automatically; cancellation cannot close a filled order."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from matchtrader.capture.route import RouteConfig
from matchtrader.dashboard.controller import DashboardController
from tests.capture.test_unwind import Broker
from tests.dashboard.test_copy_controls import signal


@pytest.fixture
def controller(settings, tmp_path):
    route = RouteConfig(machine='qt', connection_id='connection', account_id='source', destination_account='123',
                        sources=['P01', 'X17', 'R01', 'MANUAL'], exclusive_destination=True, legacy_route_disabled=True,
                        symbols={'EURUSD': {'destination': 'EURUSD', 'quantity_multiplier': '1', 'max_lots': '10',
                                            'fixed_lots': '.02', 'same_price_scale': True}})
    c = DashboardController(settings, tmp_path, route=route, interactive_copying=True)
    c.api = Broker()
    c.api.connection = SimpleNamespace(account_id='123', session_expires_at=None)
    c.api.close = lambda: None
    c.connection = 'connected'
    c.running = True
    yield c
    c.close()


def arrive(c, **values):
    return c.receive_native(signal(**values).model_dump(mode='json'))


def live(c):
    c.configure_copy_controls({'mode': 'live', 'sources': {}})


def test_live_arrival_posts_saved_lots_then_cancels_exact_pending_order(controller):
    c = controller
    live(c)
    created = arrive(c)
    assert created['status'] == 'accepted'
    assert str(c.api.calls[0][1]['volume']) == '0.02'
    assert c.api.calls[0][1]['price'] == signal().price
    cancelled = arrive(c, action='CANCEL', event_id='cancel1', request_id='cancel1')
    assert cancelled['status'] == 'accepted'
    assert c.api.calls[-1] == ('CANCEL', {'instrument': 'EURUSD', 'id': 'aqua1', 'orderSide': 'BUY', 'type': 'LIMIT'})
    assert [name for name, _ in c.api.calls] == ['CREATE', 'CANCEL']


def test_cancel_after_fill_never_closes_position(controller):
    live(controller)
    arrive(controller)
    controller.api.orders = []
    result = arrive(controller, action='CANCEL', event_id='cancel1', request_id='cancel1')
    assert result['status'] == 'held'
    assert [name for name, _ in controller.api.calls] == ['CREATE']


def test_paper_records_request_and_never_contacts_broker_or_replays_on_live(controller):
    controller.api = None
    first = signal().model_dump(mode='json')
    result = controller.receive_native(first)
    assert result['status'] == 'paper'
    assert result['request']['volume'] == '0.02'
    live(controller)
    assert controller.receive_native(first)['duplicate']
    assert controller.native_store.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 0


def test_duplicate_delivery_never_posts_twice(controller):
    live(controller)
    payload = signal().model_dump(mode='json')
    controller.receive_native(payload)
    controller.receive_native(payload)
    assert len(controller.api.calls) == 1


@pytest.mark.parametrize('change', [
    {'snapshot': True}, {'emitted_at': datetime.now(UTC) - timedelta(minutes=1)},
    {'account_id': 'other'}, {'symbol': 'OTHER'}, {'source': 'UNKNOWN'},
])
def test_unmatched_or_old_arrival_does_not_post(controller, change):
    live(controller)
    assert arrive(controller, **change)['status'] == 'held'
    assert controller.api.calls == []


def test_paper_switch_stops_cancels_and_edits_or_closes_are_observations(controller):
    live(controller)
    arrive(controller)
    for action in ['EDIT', 'CLOSE']:
        arrive(controller, action=action, event_id=action, request_id=action)
    controller.configure_copy_controls({'mode': 'paper'})
    arrive(controller, action='CANCEL', event_id='cancel', request_id='cancel')
    assert [name for name, _ in controller.api.calls] == ['CREATE']


def test_uncertain_post_is_not_repeated(controller):
    live(controller)
    def fail(**kwargs):
        controller.api.calls.append(('CREATE', kwargs))
        raise TimeoutError('test')
    controller.api.create_pending_order = fail
    assert arrive(controller)['status'] == 'uncertain'
    assert arrive(controller, event_id='retry', request_id='retry')['status'] == 'held'
    assert len(controller.api.calls) == 1


def configure_signals(c):
    c.configure_signals({'machine_id': 'qt', 'source': 'chain', 'destination_account': '123',
                         'exclusive_destination': True, 'symbols': {'EURUSD': {
                             'destination': 'EURUSD', 'fixed_lots': '.02', 'order_type': 'SOURCE', 'same_price_scale': True}}})


def structured(kind='intent', identity='i1'):
    return {'machineId': 'qt', 'clientEventId': identity, 'source': 'chain', 'connectionName': 'chart',
            'kind': kind, 'label': 'life1', 'timestampUtc': datetime.now(UTC).isoformat(),
            'symbol': 'EURUSD', 'side': 'long', 'entry': '1.15', 'stopLoss': '1.1498',
            'takeProfit': '1.16', 'copyOrderType': 'LIMIT'}


def test_strategy_signal_uses_same_live_switch_and_only_cancels_pending(controller):
    configure_signals(controller)
    live(controller)
    opened = controller.receive_signals([structured()])['results'][0]
    assert opened['status'] == 'accepted'
    controller.receive_signals([structured('closed', 'closed1')])
    assert [name for name, _ in controller.api.calls] == ['CREATE']
    cancelled = controller.receive_signals([structured('cancelled', 'cancel1')])['results'][0]
    assert cancelled['status'] == 'accepted'
    assert [name for name, _ in controller.api.calls] == ['CREATE', 'CANCEL']


def test_strategy_signal_paper_formats_request_without_broker(controller):
    configure_signals(controller)
    controller.api = None
    result = controller.receive_signals([structured()])['results'][0]
    assert result['status'] == 'paper'
    assert result['copy_request']['type'] == 'LIMIT'
    assert result['copy_request']['volume'] == '0.02'


@pytest.mark.parametrize('first', ['bridge', 'signal'])
def test_same_label_on_both_ingresses_cannot_open_twice(controller, first):
    configure_signals(controller)
    live(controller)
    def bridge():
        return arrive(controller, source_label='life1')
    def strategy():
        return controller.receive_signals([structured()])['results'][0]
    initial, second = (bridge, strategy) if first == 'bridge' else (strategy, bridge)
    assert initial()['status'] == 'accepted'
    assert second()['status'] == 'held'
    assert len(controller.api.calls) == 1
    assert arrive(controller, action='CANCEL', source_label='life1', event_id='cancel', request_id='cancel')['status'] == 'accepted'
    assert [name for name, _ in controller.api.calls] == ['CREATE', 'CANCEL']
