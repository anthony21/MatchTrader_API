import base64

from matchtrader.capture.logging_store import LoggingStore


def test_opaque_bytes_retention_restart_and_pagination(tmp_path):
    store = LoggingStore(tmp_path, max_records=2, max_bytes=65536)
    original = b'\xffnot JSON\x00'
    first = store.accept(original)
    assert first['executed'] is False and first['forwarded'] is False
    assert base64.b64decode(store.feed()['records'][0]['data_base64']) == original
    store.accept(b'{"source":"X17","unknown":123,"token":"private"}')
    store.accept(b'')
    feed = store.feed(limit=1)
    assert feed['count'] == 2 and feed['evicted'] == 1
    prior = store.feed(before=feed['next_before'])['records'][0]
    assert 'private' not in prior['preview']
    assert prior['source'] == 'X17'
    store.close()
    store = LoggingStore(tmp_path, max_records=2, max_bytes=65536)
    assert store.feed()['count'] == 2
    store.accept(b'a' * 65536)
    assert store.feed()['body_bytes'] <= 65536
    store.close()
