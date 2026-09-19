import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from matchtrader.core.errors import AuthenticationError
from matchtrader.sessions.session_manager import SessionData, SessionManager


class Adapter:
    def __init__(self, clock, identity="aqua"):
        self.clock, self.identity = clock, (identity,)
        self.logins = self.refreshes = 0
        self.fail = False

    def login(self):
        self.logins += 1
        return SessionData(self.clock() + 900, ("123", "456"), "secret-token")

    def refresh(self, previous):
        self.refreshes += 1
        if self.fail:
            raise RuntimeError("secret-upstream-response")
        return SessionData(self.clock() + 900, previous.accounts, "rotated-secret")

    def execute(self, session, account_id, operation, *args, **kwargs):
        if operation == "reject":
            raise AuthenticationError("rejected")
        return account_id, session.payload


def test_registry_reuses_login_and_refreshes_exactly_three_minutes_before_expiry():
    now = [1000.0]
    manager = SessionManager(clock=lambda: now[0], automatic=False)
    aqua, gooey = Adapter(lambda: now[0]), Adapter(lambda: now[0], "gooey")
    manager.register("AQUA", "Aqua", aqua)
    manager.register("GTR", "Gooey", gooey)
    manager.connect("AQUA")
    manager.connect("AQUA")
    manager.connect("GTR")
    assert aqua.logins == gooey.logins == 1
    now[0] = 1719
    manager.renew_due()
    assert aqua.refreshes == gooey.refreshes == 0
    now[0] = 1720
    manager.renew_due()
    assert aqua.refreshes == gooey.refreshes == 1
    assert manager.execute("AQUA", "456", "balance") == ("456", "rotated-secret")
    for _ in range(12):
        now[0] += 720
        manager.renew_due()
    assert aqua.refreshes == gooey.refreshes == 13
    manager.disconnect("AQUA")
    now[0] += 720
    manager.renew_due()
    assert aqua.refreshes == 13 and gooey.refreshes == 14
    assert "secret" not in json.dumps(manager.status())
    with pytest.raises(AuthenticationError):
        manager.execute("AQUA", "123", "balance")
    manager.close()


def test_failed_renewal_pauses_requests_and_recovers_with_backoff():
    now = [1000.0]
    manager = SessionManager(clock=lambda: now[0], automatic=False)
    adapter = Adapter(lambda: now[0])
    manager.register("A", "A", adapter)
    manager.connect("A")
    adapter.fail = True
    now[0] += 720
    manager.renew_due()
    assert manager.status("A")["state"] == "retrying"
    assert "secret" not in json.dumps(manager.status())
    with pytest.raises(AuthenticationError):
        manager.execute("A", "123", "create_pending_order")
    manager.renew_due()
    assert adapter.refreshes == 1
    now[0] += 2
    adapter.fail = False
    manager.renew_due()
    assert manager.status("A")["state"] == "connected"
    manager.close()


def test_duplicate_owner_unknown_account_expiry_and_authentication_rejection():
    now = [1000.0]
    manager = SessionManager(clock=lambda: now[0], automatic=False)
    adapter = Adapter(lambda: now[0])
    manager.register("A", "A", adapter)
    with pytest.raises(ValueError):
        manager.register("B", "B", adapter)
    manager.connect("A")
    with pytest.raises(AuthenticationError):
        manager.execute("A", "999", "balance")
    with pytest.raises(AuthenticationError):
        manager.execute("A", "123", "reject")
    assert adapter.refreshes == 0
    assert manager.status("A")["state"] == "retrying"
    now[0] += 1
    manager.renew_due()
    now[0] += 901
    with pytest.raises(AuthenticationError):
        manager.execute("A", "123", "balance")
    manager.close()
    with pytest.raises(RuntimeError):
        manager.connect("A")


def test_concurrent_connect_is_single_login_and_disconnect_joins_worker():
    manager = SessionManager()
    adapter = Adapter(time.time)
    manager.register("A", "A", adapter)
    with ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(lambda _: manager.connect("A"), range(10)))
    assert adapter.logins == 1
    worker = manager._sessions["A"].worker
    manager.disconnect("A")
    assert not worker.is_alive()
    manager.connect("A")
    new_worker = manager._sessions["A"].worker
    assert new_worker is not worker and new_worker.is_alive()
    manager.close()
    assert not new_worker.is_alive()


def test_slow_request_does_not_block_scheduled_renewal():
    entered, release = Event(), Event()
    now = [1000.0]

    class SlowAdapter(Adapter):
        def execute(self, *args, **kwargs):
            entered.set()
            assert release.wait(3)

    manager = SessionManager(clock=lambda: now[0], automatic=False)
    adapter = SlowAdapter(lambda: now[0])
    manager.register("A", "A", adapter)
    manager.connect("A")
    with ThreadPoolExecutor() as executor:
        pending = executor.submit(manager.execute, "A", "123", "balance")
        try:
            assert entered.wait(1)
            now[0] += 720
            manager.renew_due()
            assert adapter.refreshes == 1
        finally:
            release.set()
        pending.result()
    manager.close()


def test_workers_refresh_without_browser_polling_and_brokers_are_independent():
    now = [1000.0]
    blocked, release, renewed = Event(), Event(), Event()

    class Slow(Adapter):
        def refresh(self, previous):
            blocked.set()
            assert release.wait(3)
            return super().refresh(previous)

    class Fast(Adapter):
        def refresh(self, previous):
            result = super().refresh(previous)
            renewed.set()
            return result

    manager = SessionManager(clock=lambda: now[0])
    manager.register("A", "A", Slow(lambda: now[0]))
    manager.register("B", "B", Fast(lambda: now[0], "other"))
    manager.connect("A")
    manager.connect("B")
    now[0] += 720
    try:
        assert blocked.wait(2)
        assert renewed.wait(1)
    finally:
        release.set()
        manager.close()
