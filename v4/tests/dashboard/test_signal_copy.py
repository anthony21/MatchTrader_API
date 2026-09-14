import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from matchtrader.dashboard.signal_copy import SignalCopy, SignalSettings
from matchtrader.models.operation import Operation


def config(**changes):
    return {
        "machine_id": "qt",
        "source": "chain",
        "connection_name": "",
        "destination_account": "demo",
        "exclusive_destination": True,
        "symbols": {
            "US TECH 100": {
                "destination": "NAS100",
                "fixed_lots": "0.2",
                "order_type": "LIMIT",
                "same_price_scale": True,
            }
        },
        **changes,
    }


def packet(**changes):
    return {
        "clientEventId": "event-one",
        "machineId": "qt",
        "source": "chain",
        "kind": "intent",
        "timestampUtc": datetime.now(UTC).isoformat(),
        "label": "box",
        "symbol": "US TECH 100",
        "side": "short",
        "entry": 100,
        "stopLoss": 105,
        "takeProfit": 95,
        "mode": "log",
        "volume": 0,
        **changes,
    }


class Broker:
    def __init__(self):
        self.calls = []

    def instruments(self):
        return [
            SimpleNamespace(
                symbol="NAS100",
                model_dump=lambda: {"volumeMin": "0.1", "volumeMax": "10", "volumeStep": "0.1"},
            )
        ]

    def create_pending_order(self, **kwargs):
        self.calls.append(kwargs)
        return Operation(status="OK", orderId="copied-order")

    open_position = create_pending_order


def test_fixed_volume_local_copy_preserves_original_and_deduplicates_variants(tmp_path):
    service = SignalCopy(tmp_path)
    service.configure(config())
    service.arm(True)
    broker = Broker()
    original = packet()
    before = deepcopy(original)
    result = service.receive([original], broker, "demo", True)
    assert result["forwarded_to_tradingbox"] is False
    assert result["results"][0]["status"] == "accepted"
    assert broker.calls == [
        {
            "instrument": "NAS100",
            "orderSide": "SELL",
            "volume": Decimal(".2"),
            "slPrice": Decimal("105"),
            "tpPrice": Decimal("95"),
            "type": "LIMIT",
            "price": Decimal("100"),
        }
    ]
    assert original == before
    duplicate = service.receive([{**original, "l2Class": "", "volume": 999}], broker, "demo", True)
    assert duplicate["results"][0]["duplicate"] and len(broker.calls) == 1
    conflict = service.receive([{**original, "entry": 101}], broker, "demo", True)
    assert conflict["results"][0]["status"] == "held" and len(broker.calls) == 1
    service.close()


def test_off_events_and_old_events_never_replay_after_arming_or_restart(tmp_path):
    service = SignalCopy(tmp_path)
    service.configure(config())
    broker = Broker()
    original = packet()
    assert service.receive([original], broker, "demo", True)["results"][0]["status"] == "held"
    service.arm(True)
    assert service.receive([original], broker, "demo", True)["results"][0]["duplicate"]
    stale = packet(clientEventId="stale", timestampUtc=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    assert service.receive([stale], broker, "demo", True)["results"][0]["status"] == "held"
    service.close()
    service = SignalCopy(tmp_path)
    assert service.settings()["live"] is False
    assert service.symbols.lookup("US TECH 100").lots == Decimal(".2")   # the map survives the restart
    service.arm(True)
    assert service.receive([original], broker, "demo", True)["results"][0]["duplicate"]
    assert not broker.calls
    service.close()


def test_closed_events_and_completed_batches_do_not_open_or_close_orders(tmp_path):
    service = SignalCopy(tmp_path)
    service.configure(config())
    service.arm(True)
    broker = Broker()
    original = packet()
    closed = packet(clientEventId="closed", kind="closed")
    results = service.receive([original, closed], broker, "demo", True)["results"]
    assert results[0]["status"] == "held" and results[1]["status"] == "captured"
    assert not broker.calls
    service.close()


def test_unknown_write_is_never_retried(tmp_path):
    service = SignalCopy(tmp_path)
    service.configure(config())
    service.arm(True)
    broker = Broker()
    original = packet()

    def timeout(**kwargs):
        broker.calls.append(kwargs)
        raise TimeoutError()

    broker.create_pending_order = timeout
    assert service.receive([original], broker, "demo", True)["results"][0]["status"] == "uncertain"
    service.close()
    service = SignalCopy(tmp_path)
    service.arm(True)
    assert service.receive([original], broker, "demo", True)["results"][0]["status"] == "uncertain"
    assert len(broker.calls) == 1
    service.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"machineId": "other"},
        {"source": "other"},
        {"symbol": "other"},
        {"side": ""},
        {"stopLoss": 90},
        {"entry": 0},
    ],
)
def test_mismatched_or_invalid_intents_never_write(tmp_path, changes):
    service = SignalCopy(tmp_path)
    service.configure(config())
    service.arm(True)
    broker = Broker()
    assert service.receive([packet(**changes)], broker, "demo", True)["results"][0]["status"] == "held"
    assert not broker.calls
    service.close()


def test_explicit_order_type_and_destination_lot_limits(tmp_path):
    with pytest.raises(ValueError):
        SignalSettings.model_validate(
            config(
                symbols={
                    "X": {"destination": "Y", "fixed_lots": 0, "order_type": "", "same_price_scale": True}
                }
            )
        )
    service = SignalCopy(tmp_path)
    value = config()
    value["symbols"]["US TECH 100"].update(fixed_lots="0.21", order_type="MARKET")
    service.configure(value)
    service.arm(True)
    broker = Broker()
    assert service.receive([packet()], broker, "demo", True)["results"][0]["status"] == "held"
    assert not broker.calls
    service.arm(False)
    value["symbols"]["US TECH 100"]["fixed_lots"] = "0.2"
    service.configure(value)
    service.arm(True)
    assert (
        service.receive([packet(clientEventId="market")], broker, "demo", True)["results"][0]["status"]
        == "accepted"
    )
    assert "price" not in broker.calls[0] and "type" not in broker.calls[0]
    service.close()


def test_source_order_type_alias_and_missing_type_are_not_guessed(tmp_path):
    service = SignalCopy(tmp_path)
    cfg = config()
    cfg['symbols']['US TECH 100']['order_type'] = 'SOURCE'
    service.configure(cfg)
    service.arm(True)
    api = Broker()
    try:
        result = service.receive([packet(orderType='STOP')], api, 'demo', True)
        assert result['results'][0]['status'] == 'accepted'
        assert len(api.calls) == 1
        result = service.receive([packet(clientEventId='no-type')], api, 'demo', True)
        assert result['results'][0]['status'] == 'held'
        assert len(api.calls) == 1
    finally:
        service.close()


class PendingBroker(Broker):
    def __init__(self):
        super().__init__()
        self.pending = []
        self.cancellations = []
        self.quote_time = int(datetime.now(UTC).timestamp() * 1000)

    def quotes(self, **kwargs):
        return [SimpleNamespace(symbol='NAS100', bid=Decimal('99'), ask=Decimal('101'), timestampMs=self.quote_time)]

    def create_pending_order(self, **kwargs):
        self.calls.append(kwargs)
        order_id = 'order-' + str(len(self.calls))
        self.pending.append(SimpleNamespace(id=order_id, symbol=kwargs['instrument'], side=kwargs['orderSide'], type=kwargs['type']))
        return Operation(status='OK', orderId=order_id)

    def active_orders(self):
        return self.pending

    def cancel_pending_order(self, **kwargs):
        self.cancellations.append(kwargs)
        self.pending = [o for o in self.pending if o.id != kwargs['id']]
        return Operation(status='OK')


def entry_service(tmp_path):
    service = SignalCopy(tmp_path)
    cfg = config(additional_sources=['panel'])
    cfg['symbols']['US TECH 100']['order_type'] = 'ENTRY'
    service.configure(cfg)
    service.arm(True)
    return service


@pytest.mark.parametrize('side,entry,sl,tp,expected', [
    ('long', 98, 95, 105, 'LIMIT'), ('long', 103, 95, 110, 'STOP'),
    ('short', 102, 110, 95, 'LIMIT'), ('short', 97, 105, 90, 'STOP')])
def test_logged_entry_uses_bid_ask_and_never_changes_source(tmp_path, side, entry, sl, tp, expected):
    service = entry_service(tmp_path)
    api = PendingBroker()
    raw = packet(side=side, entry=entry, stopLoss=sl, takeProfit=tp, volume=0, orderType='')
    original = deepcopy(raw)
    try:
        result = service.receive([raw], api, 'demo', True)['results'][0]
        assert result['status'] == 'accepted'
        assert api.calls[0]['type'] == expected and api.calls[0]['price'] == Decimal(entry)
        assert api.calls[0]['volume'] == Decimal('.2') and raw == original
    finally:
        service.close()


def test_p01_lowercase_types_preserved_and_scoped_pending_cancel(tmp_path):
    service = entry_service(tmp_path)
    api = PendingBroker()
    try:
        original = packet(source='panel', label='P01RR_1_1', orderType='stop', connectionName='')
        assert service.receive([original], api, 'demo', True)['results'][0]['status'] == 'accepted'
        assert api.calls[0]['type'] == 'STOP'
        cancel = packet(source='panel', label='P01RR_1_1', orderType='stop', kind='cancelled', clientEventId='cancel', connectionName='')
        assert service.receive([cancel], api, 'demo', True)['results'][0]['status'] == 'accepted'
        assert api.cancellations == [{'instrument':'NAS100', 'id':'order-1', 'orderSide':'SELL', 'type':'STOP'}]
        service.receive([{**cancel, 'clientEventId':'cancel-again'}], api, 'demo', True)
        assert len(api.cancellations) == 1
    finally:
        service.close()


def test_intervals_accounts_and_sources_do_not_share_cancel_links(tmp_path):
    service = entry_service(tmp_path)
    api = PendingBroker()
    try:
        original = packet(connectionName='Time - 15s', accountId='source-a')
        assert service.receive([original], api, 'demo', True)['results'][0]['status'] == 'accepted'
        for changes in [{'connectionName':'Time - 30s'}, {'accountId':'source-b'}, {'source':'panel'}, {'label':'other'}]:
            cancel = {**original, 'kind':'cancelled', 'clientEventId':str(changes), **changes}
            result = service.receive([cancel], api, 'demo', True)['results'][0]
            # Nothing we sent is linked under that scope: recorded, with the reason, and no write.
            assert result['status'] == 'captured' and 'No sent trade is linked' in result['reason']
        assert not api.cancellations
        other = {**original, 'connectionName':'Time - 30s', 'clientEventId':'other-interval', 'timestampUtc':datetime.now(UTC).isoformat()}
        assert service.receive([other], api, 'demo', True)['results'][0]['status'] == 'accepted'
        assert len(api.calls) == 2
    finally:
        service.close()


def test_cancelled_batch_never_opens_and_filled_copy_never_closes(tmp_path):
    service = entry_service(tmp_path)
    api = PendingBroker()
    try:
        original = packet()
        cancel = packet(kind='cancelled', clientEventId='cancel')
        service.receive([original, cancel], api, 'demo', True)
        assert not api.calls and not api.cancellations
        original = packet(label='fresh', clientEventId='fresh')
        assert service.receive([original], api, 'demo', True)['results'][0]['status'] == 'accepted'
        api.pending.clear()
        result = service.receive([{**original, 'kind':'cancelled', 'clientEventId':'filled-cancel'}], api, 'demo', True)['results'][0]
        assert result['status'] == 'held' and 'no longer pending' in result['reason']
        assert not api.cancellations
    finally:
        service.close()


def test_lifecycle_dedup_live_off_and_quote_freshness(tmp_path):
    service = entry_service(tmp_path)
    api = PendingBroker()
    try:
        original = packet()
        service.receive([original], api, 'demo', True)
        result = service.receive([{**original, 'clientEventId':'different-id'}], api, 'demo', True)['results'][0]
        assert result['status'] == 'held' and len(api.calls) == 1
        # The owner's rule is asymmetric: the live switch gates opening, never unwinding. The pending
        # order this module placed exists at the broker, so its cancel acts with the switch off.
        service.arm(False)
        result = service.receive([packet(kind='cancelled', clientEventId='off-cancel')], api, 'demo', True)['results'][0]
        assert result['status'] == 'accepted' and api.cancellations == [
            {'instrument': 'NAS100', 'id': 'order-1', 'orderSide': 'SELL', 'type': 'LIMIT'}]
        # ...but it never acts without the connected destination, and never twice.
        disconnected = service.receive([packet(kind='cancelled', clientEventId='off-cancel-2')], None, 'demo', False)['results'][0]
        assert disconnected['status'] == 'held' and len(api.cancellations) == 1
        service.arm(True)
        api.quote_time -= 60000
        result = service.receive([packet(label='stale-quote', clientEventId='stale-quote')], api, 'demo', True)['results'][0]
        assert result['status'] == 'held' and len(api.calls) == 1
    finally:
        service.close()


def test_cancel_uncertain_survives_restart_without_retry(tmp_path):
    service = entry_service(tmp_path)
    api = PendingBroker()
    original = packet()
    service.receive([original], api, 'demo', True)
    def timeout(**kwargs):
        api.cancellations.append(kwargs)
        raise TimeoutError()
    api.cancel_pending_order = timeout
    cancel = packet(kind='cancelled', clientEventId='cancel')
    assert service.receive([cancel], api, 'demo', True)['results'][0]['status'] == 'uncertain'
    service.close()
    service = SignalCopy(tmp_path)
    service.arm(True)
    try:
        again = packet(kind='cancelled', clientEventId='another-cancel')
        assert service.receive([again], api, 'demo', True)['results'][0]['status'] == 'held'
        assert len(api.cancellations) == 1
    finally:
        service.close()


def test_x17_attribution_and_same_batch_interval_isolation(tmp_path):
    service = entry_service(tmp_path)
    service.arm(False)
    cfg = service.settings()['config']
    cfg['x17_only'] = True
    service.configure(cfg)
    service.arm(True)
    api = PendingBroker()
    try:
        assert service.receive([packet()], api, 'demo', True)['results'][0]['status'] == 'held'
        intent = packet(clientEventId='x17', detail='x17-spine bar=1', connectionName='Time - 15s')
        other_close = packet(kind='closed', clientEventId='closed-30s', connectionName='Time - 30s')
        assert service.receive([intent, other_close], api, 'demo', True)['results'][0]['status'] == 'accepted'
        assert len(api.calls) == 1
    finally:
        service.close()


def test_cancel_pending_flag_is_retired_and_old_settings_still_load(tmp_path):
    value = SignalSettings.model_validate(config(cancel_pending=True))
    assert 'cancel_pending' not in value.model_dump()
    (tmp_path / 'signal-copy-settings.json').write_text(json.dumps(config(cancel_pending=False)))
    service = SignalCopy(tmp_path)
    try:
        assert service.config is not None and 'cancel_pending' not in service.settings()['config']
        with pytest.raises(ValueError):
            SignalSettings.model_validate(config(unknown_switch=True))
    finally:
        service.close()


def test_unwind_signals_act_on_the_ledger_without_any_switch_and_dedupe_redelivery(tmp_path):
    from matchtrader.capture.event import CaptureEvent
    from tests.capture.test_unwind import LABEL, Broker, sent

    event = CaptureEvent(
        event_id='event1', machine='qt', connection_id='connection', account_id='source', order_id='order1',
        request_id='run:1', emitted_at=datetime.now(UTC), kind='ACCEPTED', action='CREATE', source='X17',
        symbol='EURUSD', side='BUY', order_type='LIMIT', quantity='1', price='1.15000', sl='1.14980', tp='1.16',
    )
    broker = Broker()
    store, trade_id = sent(tmp_path / 'ledger', event, broker)
    service = SignalCopy(tmp_path / 'relay', ledger=store)  # never configured, never armed
    try:
        cancel = packet(kind='cancelled', clientEventId='cancel-1', label=LABEL, symbol='EURUSD')
        result = service.receive([cancel], broker, 'demo', True)['results'][0]
        assert result['status'] == 'accepted' and result['destination_account'] == 'demo'
        assert result['copy_request']['id'] == 'aqua1' and result['copy_response']['status'] == 'OK'
        assert broker.writes() == ['CANCEL'] and store.trade(trade_id)['state'] == 'resolved'
        # Redelivery of the same signal is a duplicate: nothing is evaluated again.
        again = service.receive([cancel], broker, 'demo', True)['results'][0]
        assert again['duplicate'] and again['status'] == 'accepted' and broker.writes() == ['CANCEL']
        # A closed signal for an unknown lifecycle is recorded with the reason and touches nothing.
        other = service.receive([packet(kind='closed', clientEventId='closed-1', label='nobody')],
                                broker, 'demo', True)['results'][0]
        assert other['status'] == 'captured' and "No sent trade is linked to lifecycle 'nobody'" in other['reason']
        unlabelled = service.receive([packet(kind='closed', clientEventId='closed-2', label='')],
                                     broker, 'demo', True)['results'][0]
        assert unlabelled['status'] == 'captured' and 'no lifecycle label' in unlabelled['reason']
        assert broker.writes() == ['CANCEL']
        # An unavailable ledger leaves completion unconfirmed; this failure writes nothing.
        store.close()
        broken = service.receive([packet(kind='cancelled', clientEventId='cancel-3', label=LABEL, symbol='EURUSD')],
                                 broker, 'demo', True)['results'][0]
        assert broken['status'] == 'uncertain' and 'ProgrammingError' in broken['reason'] and LABEL in broken['reason']
        assert broker.writes() == ['CANCEL']
    finally:
        service.close()
