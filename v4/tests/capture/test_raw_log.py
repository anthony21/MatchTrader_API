import json

from matchtrader.capture.raw_log import RawLog


def test_bounds_rollover_and_close():
    log = RawLog(max_entries=2, max_bytes=600)
    for n in range(8):
        log.append('in', 'websocket', {'n': n})
    snapshot = log.stream_snapshot()
    assert len(snapshot['events']) <= 2
    assert snapshot['bytes'] <= 600
    assert json.loads(snapshot['events'][0]['raw']) == {'n': 7}
    assert snapshot['evicted'] >= 6
    assert log.stream_snapshot(snapshot['revision'], timeout=0) == {'revision': snapshot['revision']}
    log.close()
    assert log.stream_snapshot() is None


def test_redacts_malformed_secrets_truncates_and_omits_binary():
    log = RawLog()
    log.append('in', 'websocket', '{"token":"private", "nested":{"password":"hidden"}, "bad": Bearer secret', 'secret')
    text = log.stream_snapshot()['events'][0]['raw']
    assert 'private' not in text and 'hidden' not in text and 'secret' not in text
    log.append('in', 'websocket', '{"apiKey":"hidden-key","cookie":"hidden-cookie"}')
    assert 'hidden-' not in log.stream_snapshot()['events'][0]['raw']
    log.append('in', 'websocket', 'x' * 40000)
    assert log.stream_snapshot()['events'][0]['truncated']
    log.append('in', 'websocket', b'private-binary')
    assert 'private-binary' not in log.stream_snapshot()['events'][0]['raw']
