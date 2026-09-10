"""Bounded, process-local dispatch spans, using one monotonic clock per receiver."""

from collections import deque
from contextvars import ContextVar
from math import ceil
from threading import Lock
from time import perf_counter_ns

_current = ContextVar('capture_dispatch_sample', default=None)


def mark(name):
    sample = _current.get()
    if sample is not None:
        sample['spans_ns'].setdefault(name, perf_counter_ns())


def trace(name, info):
    # Ignore info: it can contain request headers, credentials and socket objects.
    if name.endswith('send_request_headers.started'):
        mark('write_started')
    elif name.endswith('send_request_body.complete'):
        mark('body_complete')
    elif name.endswith('connect_tcp.started'):
        mark('tcp_connect')
    elif name.endswith('start_tls.started'):
        mark('tls_start')


def active():
    return _current.get() is not None


class DispatchMetrics:
    def __init__(self, limit=500):
        self.samples = deque(maxlen=limit)
        self.lock = Lock()

    def run(self, event, received_ns, validated_ns, callback):
        sample = {'event_id': event.event_id, 'action': event.action, 'trade_id': None,
                  'spans_ns': {'received': received_ns, 'validated': validated_ns}}
        token = _current.set(sample)
        try:
            mark('worker_start')
            result = callback()
            sample.update(trade_id=result.get('trade_id'), status=result['status'], duplicate=result['duplicate'])
            return result
        except Exception:
            sample['status'] = 'no_ack'
            raise
        finally:
            mark('finished')
            _current.reset(token)
            spans = sample.pop('spans_ns')
            sample['stages_ms'] = {k: round((v - received_ns) / 1e6, 3) for k, v in spans.items()}
            sample['dispatch_ms'] = sample['stages_ms'].get('write_started')
            sample['under_10ms'] = sample['dispatch_ms'] < 10 if sample['dispatch_ms'] is not None else None
            with self.lock:
                self.samples.append(sample)

    def snapshot(self):
        with self.lock:
            rows = list(self.samples)
        values = sorted(row['dispatch_ms'] for row in rows if row['dispatch_ms'] is not None)
        def percentile(p):
            return values[max(0, ceil(len(values) * p) - 1)] if values else None
        return {'window': len(rows), 'writes_measured': len(values),
                'no_write_measurement': len(rows) - len(values),
                'under_10ms_pct': round(100 * sum(v < 10 for v in values) / len(values), 1) if values else None,
                'p50_ms': percentile(.5), 'p95_ms': percentile(.95), 'p99_ms': percentile(.99),
                'max_ms': max(values) if values else None, 'latest': rows[-1] if rows else None}
