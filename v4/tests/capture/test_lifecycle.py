import os

import pytest

from matchtrader.capture.lifecycle import stopping


def test_local_stop_flag_and_no_automatic_shutdown(tmp_path, monkeypatch):
    monkeypatch.delenv('HCAMM_CONTROL_LOCK', raising=False)
    flag = tmp_path / 'stop'
    assert not stopping(flag)
    flag.touch()
    assert stopping(flag)


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher lock")
def test_launcher_lock_controls_child_lifetime(tmp_path, monkeypatch):
    import msvcrt
    flag = tmp_path / 'launcher.lock'
    flag.write_bytes(b'0')
    monkeypatch.setenv('HCAMM_CONTROL_LOCK', str(flag))
    with flag.open('r+b') as stream:
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        assert not stopping()
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    assert stopping()
