"""Session tokens renew on their own timer through the controller's keeper, never by polling."""
from types import SimpleNamespace

from matchtrader.dashboard.controller import DashboardController


class Owner:
    def __init__(self, due, fail=False):
        self.due, self.fail, self.calls = due, fail, 0
        self.connection = SimpleNamespace(account_id='123', session_expires_at=None, renew_if_due=self._renew)

    def _renew(self, margin_seconds=90):
        self.calls += 1
        if self.fail:
            raise TimeoutError('broker')
        return self.due

    def close(self):
        pass


def test_keeper_thread_starts_with_the_controller_and_stops_on_close(tmp_path, settings):
    controller = DashboardController(settings, tmp_path / 'data')
    try:
        assert controller._keeper.is_alive() and controller._keeper.daemon
    finally:
        controller.close()
    assert controller._closing.is_set()
    controller._keeper.join(timeout=2)
    assert not controller._keeper.is_alive()


def test_one_pass_renews_only_owners_whose_timer_is_up_and_pushes_the_result(tmp_path, settings):
    controller = DashboardController(settings, tmp_path / 'data')
    pushes = []
    controller.native_store.notify_stream = lambda: pushes.append(1)
    try:
        assert controller.refresh_sessions_once() == ([], [])            # nothing connected: nothing asked
        idle = Owner(due=False)
        controller.api, controller.connection = idle, 'connected'
        assert controller.refresh_sessions_once() == ([], []) and idle.calls == 1 and not pushes
        assert controller.token_message == ''                              # a valid token is left alone
        due = Owner(due=True)
        controller.api = due
        assert controller.refresh_sessions_once() == (['primary'], [])
        assert controller.token_message.startswith('Token refreshed automatically at') and pushes == [1]
        failing = Owner(due=True, fail=True)
        controller.api = failing
        assert controller.refresh_sessions_once() == ([], ['primary (TimeoutError)'])
        assert 'refresh failed' in controller.token_message and 'Refresh token' in controller.token_message
        controller.connection = 'disconnected'
        assert controller.refresh_sessions_once() == ([], []) and failing.calls == 1
    finally:
        controller.api = None
        controller.close()
