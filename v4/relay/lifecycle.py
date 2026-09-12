"""Local stop signal; a launcher disappearing also stops its child services."""
import os
from pathlib import Path


def stopping(flag=None):
    if flag and flag.exists():
        return True
    control_lock = os.environ.get('HCAMM_CONTROL_LOCK')
    if not control_lock or os.name != 'nt':
        return False
    import msvcrt
    try:
        with Path(control_lock).open('r+b') as stream:
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return False  # The user-facing launcher still owns this lock.
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            return True
    except FileNotFoundError:
        return True
