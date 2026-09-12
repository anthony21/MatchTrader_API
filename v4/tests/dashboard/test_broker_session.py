"""The login, balance and order routes share an application-scoped connection."""
import base64
import json
from types import SimpleNamespace

import pytest

from matchtrader.dashboard.broker_profiles import BrokerProfiles
from matchtrader.dashboard.broker_session import BrokerSession
from matchtrader.dashboard.controller import DashboardController
from matchtrader.dashboard.server import Handler
from matchtrader.models.authentication import Authentication
from matchtrader.models.balance import Balance


def auth():
    part = base64.urlsafe_b64encode(json.dumps({'exp': 2000000000}).encode()).decode().rstrip('=')
    return Authentication.model_validate({'token': f'h.{part}.s', 'accounts': [{'tradingAccountId': '123'}]})


class API:
    instances = []

    def __init__(self, settings):
        self.settings, self.closed = settings, False
        self.connection = SimpleNamespace(account_id=settings.account_id, session_expires_at='2030-01-01T00:00:00+00:00')
        self.calls = []
        self.instances.append(self)

    def discover_accounts(self):
        self.calls.append('discover')
        return auth()

    def use_login(self, authentication):
        self.calls.append('reuse')
        return authentication

    def login(self):
        raise AssertionError('The successful discovery login must be reused')

    def balance(self):
        self.calls.append('balance')
        return Balance(balance='100', equity='100', currency='USD')

    def active_orders(self):
        self.calls.append('orders')
        return []

    def open_positions(self):
        self.calls.append('positions')
        return []

    def close(self):
        self.closed = True


def test_login_during_capture_injects_one_account_session_for_balance_and_routes(settings, tmp_path):
    API.instances = []
    session = BrokerSession()
    c = DashboardController(settings, tmp_path, api_factory=API, broker_session=session)
    profiles = BrokerProfiles({'AQF': settings}, c, api_factory=API)
    c.broker_profiles = profiles
    c.running = True
    try:
        assert profiles.action('AQF', 'login')['completed']
        api = session.require('123')
        assert c.running and c.connection == 'connected'
        assert c.api is api and not api.closed
        assert profiles.snapshot()['profiles'][0]['balance']['balance'] == '100'
        assert len(API.instances) == 2  # discovery owner + one account owner
        assert API.instances[0].closed
        for _ in range(3):
            Handler.dashboard_sections(c, [])
            c.refresh_orders()
            c.refresh_positions()
            assert c.api is session.require('123') is api
        profiles.action('AQF', 'login')
        assert c.api is api and len(API.instances) == 2
        assert 'discover' not in api.calls
        with pytest.raises(ValueError):
            session.require('other-account')
    finally:
        c.close()
    assert api.closed and session.api is None


def test_temporary_read_failure_does_not_destroy_secondary_connection(settings):
    session = API(settings)
    profiles = BrokerProfiles({'GTR': settings}, None, api_factory=API)
    entry = profiles.entries['GTR']
    entry.update(api=session, state='connected', authentication=auth(), accounts=[{'id': '123'}])
    def failure():
        raise TimeoutError('private request')
    session.balance = failure
    profiles.action('GTR', 'refresh')
    assert entry['api'] is session and not session.closed
    assert entry['authentication'] is not None
    assert 'private request' not in entry['error']
    session.balance = lambda: Balance(balance='100', equity='100', currency='USD')
    profiles.action('GTR', 'refresh')
    assert entry['data']['balance']['balance'] == '100'
    profiles.close()


def test_active_account_session_outlives_discovery_token(settings):
    api = API(settings)
    profiles = BrokerProfiles({'GTR': settings}, None, api_factory=API)
    expired = Authentication.model_validate({'token': 'h.eyJleHAiOjF9.s'})
    profiles.entries['GTR'].update(api=api, state='connected', authentication=expired, accounts=[{'id': '123'}])
    row = profiles.snapshot()['profiles'][0]
    assert row['login_status'] == 'connected' and row['accounts']
    profiles.close()
