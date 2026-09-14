from matchtrader.models.operation import Operation
from matchtrader.signals import BrokerDispatcher, SignalEngine, parse_signal
from tests.signals.helpers import Broker, context, lane, raw, symbols


class RawLog:
    def __init__(self):
        self.rows = []

    def append(self, direction, kind, body):
        self.rows.append((direction, kind, body))


def test_dispatcher_only_calls_the_broker_and_reports_accepted_or_uncertain():
    broker = Broker()
    plan = SignalEngine(lane(), symbols()).decide(parse_signal(raw()), context(api=broker))
    log = RawLog()
    outcome = BrokerDispatcher(raw_log=log).send(plan, broker, correlation="k")
    assert outcome.decision == "accepted" and outcome.response["orderId"] == "order-1" and len(broker.calls) == 1
    assert outcome.request["volume"] == "0.2" and [r[0] for r in log.rows] == ["out", "in"]

    def timeout(**kwargs):
        raise TimeoutError()
    broker.create_pending_order = timeout
    outcome = BrokerDispatcher().send(plan, broker, correlation="k")
    assert outcome.decision == "uncertain" and "TimeoutError" in outcome.reason and outcome.response == {"error_type": "TimeoutError"}
    broker.create_pending_order = lambda **kwargs: Operation(status="REJECTED")
    assert BrokerDispatcher().send(plan, broker, correlation="k").decision == "uncertain"


def test_dispatcher_cancel_sends_exactly_the_prepared_request():
    class Cancelling(Broker):
        def cancel_pending_order(self, **kwargs):
            self.calls.append(kwargs)
            return Operation(status="OK")
    broker = Cancelling()
    request = {"instrument": "NAS100", "id": "order-1", "orderSide": "SELL", "type": "LIMIT"}
    outcome = BrokerDispatcher().cancel(request, broker, correlation="c")
    assert outcome.decision == "accepted" and broker.calls == [request]
    broker.cancel_pending_order = lambda **kwargs: Operation(status="PENDING")
    assert BrokerDispatcher().cancel(request, broker, correlation="c").decision == "uncertain"
