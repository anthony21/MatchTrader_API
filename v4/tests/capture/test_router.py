from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from matchtrader.capture import CaptureStore
from matchtrader.capture.router import CaptureRouter
from matchtrader.models.operation import Operation
from matchtrader.models.position import Position


def configured(tmp_path, route):
    router = CaptureRouter(CaptureStore(tmp_path), route)
    router.armed = router.demo_verified = True
    return router


def test_p01_copy_uses_submitted_brackets_and_manual_cancel_follows_mapping(tmp_path, route, event, broker):
    route.sources = ["P01"]
    router = configured(tmp_path, route)
    event = event.model_copy(update={"source": "P01", "source_label": "P01RR_120001_5"})
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "accepted" and result["broker_order_id"] == "aqua1"
    assert broker.calls[0][1]["slPrice"] == event.sl
    cancel = event.model_copy(
        update={"action": "CANCEL", "event_id": "cancel", "request_id": "c1", "source": "UNKNOWN"}
    )
    assert router.receive(cancel.model_dump(), broker, "demo")["status"] == "accepted"
    router.store.close()


def test_enable_does_not_replay_queued_off_period(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    router.armed_at = datetime.now(UTC)
    assert router.receive(event.model_dump(), broker, "demo")["status"] == "held"
    assert not broker.calls
    router.store.close()


def test_create_edit_cancel_same_id_with_duplicate_delivery(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "accepted"
    assert router.receive(event.model_dump(), broker, "demo")["duplicate"]
    replay = event.model_copy(update={"event_id": "new-event-id"})
    assert router.receive(replay.model_dump(), broker, "demo")["status"] == "held"
    for i, action in enumerate(["EDIT", "CANCEL"], 2):
        updated = event.model_copy(update={"event_id": f"e{i}", "request_id": f"run:{i}", "action": action})
        accepted = router.receive(updated.model_dump(), broker, "demo")
        assert accepted["trade_id"] == result["trade_id"] and accepted["status"] == "accepted"
    assert [c[0] for c in broker.calls] == ["CREATE", "EDIT", "CANCEL"]
    assert broker.calls[1][1]["id"] == "aqua1"
    trade = router.store.trade(result["trade_id"])
    assert trade["state"] == "resolved" and trade["resolved_at"]
    router.store.close()


def test_uncertain_write_never_retried_after_restart(tmp_path, route, event, broker):
    router = configured(tmp_path, route)

    def timeout(**kwargs):
        broker.calls.append(("CREATE", kwargs))
        raise TimeoutError()

    broker.create_pending_order = timeout
    assert router.receive(event.model_dump(), broker, "demo")["status"] == "uncertain"
    router.store.close()
    router = configured(tmp_path, route)
    assert (
        router.receive(event.model_copy(update={"event_id": "different"}).model_dump(), broker, "demo")[
            "status"
        ]
        == "held"
    )
    assert len(broker.calls) == 1
    router.store.close()


def test_broker_rejection_reason_is_recorded_never_as_bare_unknown(tmp_path, route, event, broker):
    from matchtrader.core.errors import APIError

    router = configured(tmp_path, route)
    reason = {"origin": "broker", "code": "MARGIN_001", "summary": "Not enough free margin",
              "evidence": "broker write response"}

    def rejected(**kwargs):
        broker.calls.append(("CREATE", kwargs))
        raise APIError("Operation did not report OK", reason=reason)

    broker.create_pending_order = rejected
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "uncertain"
    assert result["reason"] == "Write outcome requires broker reconciliation; not retried"
    row = router.store.db.execute(
        "SELECT * FROM outcome_reasons WHERE trade_id=?", (result["trade_id"],),
    ).fetchone()
    assert row["origin"] == "broker"
    assert row["code"] == "MARGIN_001"
    assert row["summary"] == "Not enough free margin"
    assert router.store.trade(result["trade_id"])["state"] == "uncertain"
    router.store.close()


def test_unlabeled_exception_still_records_an_investigable_reason(tmp_path, route, event, broker):
    router = configured(tmp_path, route)

    def broken(**kwargs):
        broker.calls.append(("CREATE", kwargs))
        raise RuntimeError("boom, no .reason attribute here")

    broker.create_pending_order = broken
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "uncertain"
    assert result["reason"] == "Write outcome requires broker reconciliation; not retried"
    row = router.store.db.execute(
        "SELECT * FROM outcome_reasons WHERE trade_id=?", (result["trade_id"],),
    ).fetchone()
    # No structured evidence exists for this bare exception: origin='transport' would assert
    # a wire cause that was never established, so it must be labelled 'unconfirmed' instead.
    assert row["origin"] == "unconfirmed"
    assert "RuntimeError" in row["summary"]
    assert row["origin"] and row["code"] and row["evidence"]
    assert row["summary"] != "unknown"
    router.store.close()


def test_string_reason_attribute_never_crashes_the_uncertain_transition(tmp_path, route, event, broker):
    # urllib.error.URLError and ssl.SSLError both carry a `.reason` that is a *string*, not
    # a dict. getattr(exc, "reason", None) is duck-typed, so a naive fallback would try
    # reason.get(...) on a str, raise AttributeError, and skip the uncertain transition
    # entirely - losing the record. Reproduced here without importing urllib/ssl directly.
    class FakeURLError(Exception):
        def __init__(self, reason):
            super().__init__(reason)
            self.reason = reason

    def broken(**kwargs):
        broker.calls.append(("CREATE", kwargs))
        raise FakeURLError("Name or service not known")

    router = configured(tmp_path, route)
    broker.create_pending_order = broken
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "uncertain"
    assert result["reason"] == "Write outcome requires broker reconciliation; not retried"
    row = router.store.db.execute(
        "SELECT * FROM outcome_reasons WHERE trade_id=?", (result["trade_id"],),
    ).fetchone()
    assert row is not None
    assert row["origin"] and row["code"] and row["evidence"]
    assert "Name or service not known" in row["summary"]
    trade = router.store.trade(result["trade_id"])
    assert trade["state"] == "uncertain"
    attempt = router.store.db.execute(
        "SELECT state FROM attempts WHERE trade_id=?", (result["trade_id"],),
    ).fetchone()
    assert attempt["state"] == "uncertain"
    router.store.close()


def test_local_check_failure_after_broker_ok_is_recorded_with_local_origin(tmp_path, route, event, broker):
    # The broker replied OK but with neither an order nor a position id - a router-raised
    # RuntimeError, not a wire failure. It must be labelled origin='local', not 'transport',
    # and must keep the RuntimeError's own message rather than discarding it.
    from matchtrader.models.operation import Operation

    router = configured(tmp_path, route)
    broker.create_pending_order = lambda **kwargs: Operation(status="OK")
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "uncertain"
    row = router.store.db.execute(
        "SELECT * FROM outcome_reasons WHERE trade_id=?", (result["trade_id"],),
    ).fetchone()
    assert row["origin"] == "local"
    assert row["code"] == "RuntimeError"
    assert "Broker identity missing after submission" in row["summary"]
    router.store.close()


def test_local_persistence_failure_after_broker_success_is_recorded_as_local(
    tmp_path, route, event, broker
):
    # The broker already confirmed the write; only our own store.update() call afterward
    # fails. That must be labelled origin='local', never 'transport' - transport must mean
    # the wire and nothing else.
    router = configured(tmp_path, route)
    original_update = router.store.update
    calls = []

    def flaky_update(identity, **values):
        calls.append(values)
        if len(calls) == 2:
            raise RuntimeError("simulated local persistence failure")
        return original_update(identity, **values)

    router.store.update = flaky_update
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "uncertain"
    row = router.store.db.execute(
        "SELECT * FROM outcome_reasons WHERE trade_id=?", (result["trade_id"],),
    ).fetchone()
    assert row["origin"] == "local"
    assert row["code"] == "RuntimeError"
    assert "simulated local persistence failure" in row["summary"]
    router.store.close()


def test_reason_construction_failure_still_transitions_to_uncertain_and_logs(
    tmp_path, route, event, broker, caplog
):
    # Building the reason (e.g. calling str() on the exception) must not be able to escape
    # and skip the uncertain state transitions - the user's rule that a diagnostic failure
    # must never leave a trade stuck, and must never be silently swallowed either.
    class ExplodingStr(Exception):
        def __str__(self):
            raise RuntimeError("str() blew up")

    def broken(**kwargs):
        broker.calls.append(("CREATE", kwargs))
        raise ExplodingStr()

    router = configured(tmp_path, route)
    broker.create_pending_order = broken
    with caplog.at_level("ERROR", logger="matchtrader.capture.router"):
        result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "uncertain"
    assert result["reason"] == "Write outcome requires broker reconciliation; not retried"
    trade = router.store.trade(result["trade_id"])
    assert trade["state"] == "uncertain"
    attempt = router.store.db.execute(
        "SELECT state FROM attempts WHERE trade_id=?", (result["trade_id"],),
    ).fetchone()
    assert attempt["state"] == "uncertain"
    assert router.store.db.execute(
        "SELECT 1 FROM outcome_reasons WHERE trade_id=?", (result["trade_id"],),
    ).fetchone() is None
    assert any("Outcome reason not recorded" in r.message for r in caplog.records)
    router.store.close()


def test_reason_insert_failure_is_logged_with_trade_action_and_reason_origin(
    tmp_path, route, event, broker, caplog
):
    # A failed insert must never be a silent pass: the explanation has to survive somewhere,
    # correlated to the trade/action and carrying the reason's own origin/code, even when the
    # row itself is lost.
    from matchtrader.core.errors import APIError

    router = configured(tmp_path, route)
    reason = {"origin": "broker", "code": "MARGIN_001", "summary": "Not enough free margin",
              "evidence": "broker write response"}

    def rejected(**kwargs):
        broker.calls.append(("CREATE", kwargs))
        raise APIError("Operation did not report OK", reason=reason)

    broker.create_pending_order = rejected

    def broken_record_reason(*args, **kwargs):
        raise ValueError("simulated storage failure")

    router.store.record_reason = broken_record_reason
    with caplog.at_level("ERROR", logger="matchtrader.capture.router"):
        result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "uncertain"
    trade = router.store.trade(result["trade_id"])
    assert trade["state"] == "uncertain"
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        result["trade_id"] in m and "MARGIN_001" in m and "broker" in m for m in messages
    )
    router.store.close()


@pytest.mark.parametrize(
    "change",
    [
        {"snapshot": True},
        {"source": "UNKNOWN"},
        {"account_id": "other"},
        {"quantity": Decimal("1000")},
        {"order_type": "STOP_LIMIT"},
        {"brackets_absolute": False},
        {"order_id": ""},
        {"action": "CANCEL"},
        {"symbol": "ES"},
        {"sl": Decimal("1.16")},
        {"emitted_at": datetime.now(UTC) - timedelta(minutes=1)},
    ],
)
def test_holds_before_any_broker_write(tmp_path, route, event, broker, change):
    router = configured(tmp_path, route)
    assert router.receive(event.model_copy(update=change).model_dump(), broker, "demo")["status"] == "held"
    assert not broker.calls
    router.store.close()


def test_snapshots_signals_and_request_intent_cannot_place_orders(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    for kind in ["ORDER", "FILL", "POSITION", "SIGNAL", "REQUEST", "REJECTED"]:
        result = router.receive(
            event.model_copy(update={"event_id": kind, "kind": kind}).model_dump(), broker, "demo"
        )
        assert result["status"] == "captured"
    assert not broker.calls
    router.store.close()


def test_market_fill_links_source_position_and_close(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    event = event.model_copy(update={"order_type": "MARKET"})
    result = router.receive(event.model_dump(), broker, "demo")
    assert result["status"] == "accepted"
    broker.positions = [Position(id="position1", symbol="EURUSD", side="BUY", volume=".01", openPrice="1.15")]
    router.receive(
        event.model_copy(
            update={"event_id": "fill", "kind": "FILL", "position_id": "qtposition"}
        ).model_dump(),
        broker,
        "demo",
    )
    close = event.model_copy(
        update={
            "event_id": "close",
            "request_id": "run:2",
            "order_id": "",
            "position_id": "qtposition",
            "action": "CLOSE",
        }
    )
    assert router.receive(close.model_dump(), broker, "demo")["status"] == "accepted"
    assert broker.calls[-1][1]["positionId"] == "position1"
    assert router.store.trade(result["trade_id"])["state"] == "resolved"
    router.store.close()


def test_position_only_response_does_not_invent_order_id(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    broker.open_position = lambda **kwargs: Operation(positionId='only-position')
    market = event.model_copy(update={'order_type': 'MARKET'})
    result = router.receive(market.model_dump(), broker, 'demo')
    assert result['status'] == 'accepted'
    assert result['broker_order_id'] == ''
    assert result['broker_position_id'] == 'only-position'
    assert router.receive(market.model_copy(update={'event_id': 'duplicate-create'}).model_dump(),
                          broker, 'demo')['status'] == 'held'
    router.store.close()


def test_partial_close_audit_and_cancel_does_not_resolve_filled_position(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    created = event.model_copy(update={'quantity': Decimal('2')})
    identity = router.receive(created.model_dump(), broker, 'demo')['trade_id']
    broker.positions = [Position(id='filled', symbol='EURUSD', side='BUY', volume='.02',
                                 openPrice='1.15', orderId='aqua1')]
    close = created.model_copy(update={'event_id': 'partial', 'request_id': 'partial',
                                       'action': 'CLOSE', 'quantity': Decimal('1')})
    assert router.receive(close.model_dump(), broker, 'demo')['status'] == 'accepted'
    assert broker.calls[-1][0] == 'PARTIAL'
    assert broker.calls[-1][1]['positionId'] == 'filled'
    cancel = created.model_copy(update={'event_id': 'cancel', 'request_id': 'cancel', 'action': 'CANCEL'})
    assert router.receive(cancel.model_dump(), broker, 'demo')['status'] == 'accepted'
    assert router.store.trade(identity)['state'] == 'open'
    actions = router.store.mapping_view('demo')[0]['actions']
    assert len(actions) == 3
    partial = next(a for a in actions if a['action'] == 'CLOSE')
    assert partial['request']['positionId'] == 'filled'
    assert partial['request']['volume'] == '0.01'
    assert partial['outcome'] == 'accepted'
    router.store.close()


def test_source_split_holds_close_without_allocating_by_guess(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    market = event.model_copy(update={'order_type': 'MARKET'})
    router.receive(market.model_dump(), broker, 'demo')
    for index in (1, 2):
        router.receive(market.model_copy(update={'event_id': f'fill{index}', 'kind': 'FILL',
                        'position_id': f'qt{index}', 'execution_id': f'ex{index}'}).model_dump(), broker, 'demo')
    broker.positions = [Position(id='position1', symbol='EURUSD', side='BUY', volume='.01', openPrice='1.15')]
    result = router.receive(market.model_copy(update={'event_id': 'close', 'request_id': 'close',
                            'action': 'CLOSE'}).model_dump(), broker, 'demo')
    assert result['status'] == 'held' and 'Split' in result['reason']
    assert len(broker.calls) == 1
    router.store.close()


def test_destination_merge_blocks_full_close_of_one_trade(tmp_path, route, event, broker):
    router = configured(tmp_path, route)
    counter = []
    def create(**kwargs):
        counter.append(kwargs)
        return Operation(orderId=f'broker{len(counter)}', positionId='merged')
    broker.open_position = create
    market = event.model_copy(update={'order_type': 'MARKET'})
    router.receive(market.model_dump(), broker, 'demo')
    router.receive(market.model_copy(update={'event_id': 'create2', 'order_id': 'qt2'}).model_dump(), broker, 'demo')
    broker.positions = [Position(id='merged', symbol='EURUSD', side='BUY', volume='.01', openPrice='1.15')]
    result = router.receive(market.model_copy(update={'event_id': 'close', 'request_id': 'close',
                            'action': 'CLOSE'}).model_dump(), broker, 'demo')
    assert result['status'] == 'held' and 'Merged' in result['reason']
    assert not broker.calls
    router.store.close()


@pytest.mark.parametrize('completed', [False, True])
def test_replay_recovers_missing_terminal_decision_without_dispatch(tmp_path, route, event, broker, completed):
    router = configured(tmp_path, route)
    if completed:
        result = router.receive(event.model_dump(), broker, 'demo')
        assert result['status'] == 'accepted'
        # Simulate a crash after attempt completion but before the event decision commit.
        with router.store.lock, router.store.db:
            router.store.db.execute("UPDATE events SET decision='captured',reason=''")
    else:
        router.store.record(event)  # Crash before any dispatch intent was claimed.
    count = len(broker.calls)
    replay = router.receive(event.model_dump(), broker, 'demo')
    assert replay['duplicate'] and len(broker.calls) == count
    assert replay['status'] == ('accepted' if completed else 'held')
    assert router.store.feed()[0]['decision'] == replay['status']
    router.store.close()


def test_quantise_prices_puts_prices_on_the_destination_grid():
    """Sources publish raw floats at their own tick; send what the broker can represent."""
    event = SimpleNamespace(side="SELL", action="CREATE", order_type="LIMIT",
                            price=77498.42683130718, sl=77498.52683130719, tp=77498.32683130717)
    graded = CaptureRouter.quantise_prices({"pricePrecision": 2}, event)
    assert (graded.price, graded.sl, graded.tp) == (
        Decimal("77498.43"), Decimal("77498.53"), Decimal("77498.33"))
    assert graded.side == "SELL" and graded.order_type == "LIMIT"


def test_quantise_prices_uses_one_decimal_where_the_broker_does():
    event = SimpleNamespace(side="SELL", price=7656.299999999985, sl=7732.175, tp=7611.425)
    graded = CaptureRouter.quantise_prices({"pricePrecision": 1}, event)
    assert (graded.price, graded.sl, graded.tp) == (
        Decimal("7656.3"), Decimal("7732.2"), Decimal("7611.4"))


def test_quantise_prices_leaves_absent_brackets_and_unknown_precision_alone():
    event = SimpleNamespace(side="BUY", price=100.987, sl=0, tp=None)
    graded = CaptureRouter.quantise_prices({"pricePrecision": 2}, event)
    assert graded.price == Decimal("100.99") and graded.sl == 0 and graded.tp is None
    untouched = CaptureRouter.quantise_prices({}, event)
    assert untouched.price == 100.987


def test_bracket_collapsing_onto_entry_after_rounding_is_refused():
    """A stop inside one tick of entry must not be sent as a valid bracket."""
    class Inst:
        def model_dump(self):
            return {"symbol": "SPX500", "volumeMin": "0.01", "volumeMax": "100",
                    "volumeStep": "0.01", "pricePrecision": 1}

    api = SimpleNamespace(instruments=lambda: [SimpleNamespace(symbol="SPX500", model_dump=Inst().model_dump)])
    event = SimpleNamespace(side="SELL", action="CREATE", order_type="LIMIT",
                            price=7656.04, sl=7656.06, tp=7656.02)
    with pytest.raises(ValueError, match="wrong side of entry"):
        CaptureRouter._validate_instrument(api, "SPX500", Decimal("0.01"), event)
