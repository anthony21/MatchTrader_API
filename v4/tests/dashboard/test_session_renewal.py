"""A per-connection SessionRenewer arms one timer, renews on the timer, and re-arms; a failure
backs off and a far expiry is capped, all without polling."""
from types import SimpleNamespace

from matchtrader.dashboard.session_renewal import SessionRenewer


class FakeTimer:
    def __init__(self, delay, fn):
        self.delay, self.fn, self.started, self.cancelled = delay, fn, False, False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


def owner(delay, due=True, fail=False):
    calls = {"renew": 0}

    def renew_if_due(margin_seconds=120):
        calls["renew"] += 1
        if fail:
            raise TimeoutError("broker")
        return due

    api = SimpleNamespace(connection=SimpleNamespace(
        renewal_delay=lambda margin_seconds=120: delay, renew_if_due=renew_if_due))
    return api, calls


def factory():
    timers = []
    return timers, (lambda d, fn: (timers.append(FakeTimer(d, fn)) or timers[-1]))


def test_arms_at_the_delay_then_fires_renews_and_rearms():
    timers, make = factory()
    api, calls = owner(300.0, due=True)
    results = []
    r = SessionRenewer("GTR", api, lambda *a: results.append(a), timer_factory=make)
    r.start()
    assert timers[-1].delay == 300.0 and timers[-1].started   # armed exactly at the 2-min-before delay
    timers[-1].fn()                                           # the timer fires
    assert calls["renew"] == 1 and results[-1] == ("GTR", True, True, "")
    assert len(timers) == 2 and timers[-1].delay == 300.0     # re-armed from the fresh expiry
    r.cancel()
    assert timers[-1].cancelled


def test_backs_off_after_a_failed_renewal_instead_of_spinning():
    timers, make = factory()
    api, _ = owner(50.0, fail=True)
    SessionRenewer("X", api, lambda *a: None, backoff=60.0, timer_factory=make).start()
    timers[-1].fn()
    assert timers[-1].delay == 60.0   # re-armed at the backoff, not the 50s delay


def test_long_delay_is_capped_so_the_os_timer_does_not_overflow():
    timers, make = factory()
    api, _ = owner(10_000_000.0)
    SessionRenewer("X", api, lambda *a: None, max_delay=3600.0, timer_factory=make).start()
    assert timers[-1].delay == 3600.0


def test_no_session_arms_nothing():
    timers, make = factory()
    api = SimpleNamespace(connection=SimpleNamespace(renewal_delay=lambda margin_seconds=120: None))
    SessionRenewer("X", api, lambda *a: None, timer_factory=make).start()
    assert timers == []
