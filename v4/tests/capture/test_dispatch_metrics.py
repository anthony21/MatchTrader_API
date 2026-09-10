from matchtrader.capture.dispatch_metrics import DispatchMetrics, active, mark, trace


def test_only_actual_transport_write_produces_latency(event, monkeypatch):
    clock = iter([1_000_000, 2_000_000, 5_000_000, 8_000_000, 9_000_000])
    monkeypatch.setattr('matchtrader.capture.dispatch_metrics.perf_counter_ns', lambda: next(clock))
    metrics = DispatchMetrics()
    def dispatch():
        assert active()
        mark('event_commit')
        trace('http11.send_request_headers.started', {'secret': 'must-not-be-recorded'})
        trace('http11.send_request_body.complete', {})
        return {'status': 'accepted', 'duplicate': False, 'trade_id': 't1'}
    metrics.run(event, 0, 500_000, dispatch)
    snapshot = metrics.snapshot()
    assert snapshot['p95_ms'] == 5
    assert snapshot['under_10ms_pct'] == 100
    assert snapshot['latest']['trade_id'] == 't1'
    assert 'secret' not in str(snapshot)
    assert not active()


def test_observations_have_no_write_latency_and_history_is_bounded(event):
    metrics = DispatchMetrics(limit=2)
    for _ in range(3):
        metrics.run(event, 0, 0, lambda: {'status': 'held', 'duplicate': False})
    snapshot = metrics.snapshot()
    assert snapshot['window'] == 2 and snapshot['writes_measured'] == 0
    assert snapshot['latest']['dispatch_ms'] is None and snapshot['p95_ms'] is None
