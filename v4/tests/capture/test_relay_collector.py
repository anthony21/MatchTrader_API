import base64

import pytest

from matchtrader.capture.relay_collector import RelayCollector
from matchtrader.capture.relay_store import RelayLogStore


def test_all_files_and_large_lines_preserved(tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    files = {'relay.log': b'startup\n', 'x17-events.jsonl': b'x' * 20000 + b'\n',
             'raw-request.jsonl': b'{"any-new-field": [1,2,3]}\n'}
    for name, data in files.items():
        (logs / name).write_bytes(data)
    receiver = RelayLogStore(tmp_path / 'receiver')
    sender = RelayCollector(logs, tmp_path / 'state.db', 'http://127.0.0.1:8765/relay/logs', 't' * 40, deliver=receiver.accept)
    while sender.poll():
        pass
    restored = {}
    for row in receiver.feed()['records']:
        restored[row['filename']] = restored.get(row['filename'], b'') + base64.b64decode(row['data_base64'])
    assert restored == files
    sender.close()
    receiver.close()


def test_lost_ack_with_file_growth_replays_identical_chunk_after_restart(tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    source = logs / 'relay.log'
    source.write_bytes(b'first partial')
    receiver = RelayLogStore(tmp_path / 'receiver')

    def lose_ack(message):
        receiver.accept(message)
        raise OSError('connection lost after commit')

    args = (logs, tmp_path / 'state.db', 'http://127.0.0.1:8765/relay/logs', 't' * 40)
    sender = RelayCollector(*args, deliver=lose_ack)
    with pytest.raises(OSError):
        sender.poll()
    sender.close()
    with source.open('ab') as output:
        output.write(b' and more\n')
    sender = RelayCollector(*args, deliver=receiver.accept)
    while sender.poll():
        pass
    rows = receiver.feed()['records']
    assert len(rows) == 2
    assert b''.join(base64.b64decode(row['data_base64']) for row in rows) == source.read_bytes()
    sender.close()
    receiver.close()


def test_bad_ack_retains_pending_and_rotation_starts_new_stream(tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    source = logs / 'relay.log'
    source.write_bytes(b'original long line\n')
    receiver = RelayLogStore(tmp_path / 'receiver')
    sender = RelayCollector(logs, tmp_path / 'state.db', 'http://127.0.0.1:8765/relay/logs', 't' * 40,
                            deliver=lambda message: {**receiver.accept(message), 'durable': False})
    with pytest.raises(ValueError):
        sender.poll()
    assert sender.db.execute('SELECT offset FROM files').fetchone()[0] == 0
    sender.deliver = receiver.accept
    sender.poll()
    source.write_bytes(b'new\n')
    sender.poll()
    assert receiver.status()['streams'] == 2
    sender.close()
    receiver.close()
