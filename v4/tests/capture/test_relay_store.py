import base64
import hashlib
from uuid import uuid4

import pytest

from matchtrader.capture.relay_store import RelayLogStore


def envelope(data=b'{"unknown-field":17}\n', **changes):
    return {'version': '1.0.0', 'stream_id': str(uuid4()), 'machine': 'test-machine',
            'filename': 'x17-events-20260911.jsonl', 'offset': 0,
            'sha256': hashlib.sha256(data).hexdigest(), 'data_base64': base64.b64encode(data).decode(), **changes}


def test_durable_exact_bytes_and_replay_across_restart(tmp_path):
    message = envelope(b'not-json\x00\xff\n')
    store = RelayLogStore(tmp_path)
    assert store.accept(message)['durable'] is True
    store.close()
    store = RelayLogStore(tmp_path)
    assert store.accept(message)['duplicate'] is True
    rows = store.feed()['records']
    assert len(rows) == 1 and rows[0]['data_base64'] == message['data_base64']
    assert store.status()['bytes'] == 11
    store.close()


def test_rejects_conflicts_gaps_and_checksum_mismatch(tmp_path):
    store = RelayLogStore(tmp_path)
    first = envelope(b'abc')
    store.accept(first)
    for invalid in (envelope(b'xyz', stream_id=first['stream_id']),
                    envelope(b'next', offset=4, stream_id=first['stream_id']),
                    envelope(sha256='wrong'), envelope(filename='../secret.log'),
                    envelope(b'x' * 8193), envelope(offset=True)):
        with pytest.raises(ValueError):
            store.accept(invalid)
    assert store.status()['chunks'] == 1
    second = envelope(b'next', offset=3, stream_id=first['stream_id'])
    assert store.accept(second)['next_offset'] == 7
    assert len(store.feed(after=1)['records']) == 1
    store.close()
