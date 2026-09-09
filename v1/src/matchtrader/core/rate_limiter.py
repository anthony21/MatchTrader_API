"""Conservative pacing shared by authentication and trading requests."""

import time
from threading import Lock
from typing import ClassVar
from weakref import WeakValueDictionary


class RateLimiter:
    _shared: ClassVar[WeakValueDictionary] = WeakValueDictionary()
    _shared_lock = Lock()

    @classmethod
    def for_origin(cls, origin, per_minute):
        """Account sessions share a conservative aggregate broker request budget."""
        with cls._shared_lock:
            limiter = cls._shared.get(origin)
            if limiter is None:
                limiter = cls(per_minute)
                cls._shared[origin] = limiter
            else:
                with limiter.lock:
                    limiter.interval = max(limiter.interval, 60 / per_minute)
            return limiter

    def __init__(self, per_minute, clock=time.monotonic, sleep=time.sleep):
        self.interval = 60 / per_minute
        self.clock, self.sleep = clock, sleep
        self.next_time = 0.0
        self.lock = Lock()

    def wait(self):
        with self.lock:
            now = self.clock()
            delay = max(0.0, self.next_time - now)
            if delay:
                self.sleep(delay)
            self.next_time = max(self.clock(), self.next_time) + self.interval
