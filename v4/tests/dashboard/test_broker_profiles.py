from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, RLock
from types import SimpleNamespace

import pytest

from matchtrader.dashboard.broker_profiles import BrokerProfiles, load_profiles
from matchtrader.models.balance import Balance
from matchtrader.models.order import Order


def test_env_profiles_do_not_inherit_credentials_and_limit_five(tmp_path, monkeypatch):
    path = tmp_path / '.env'
    path.write_text('MTR_PLATFORM_URL=https://one.example\nMTR_EMAIL=first\nMTR_ACCOUNT_ID=1\nGTR_PLATFORM_URL=https://two.example\nGTR_ACCOUNT_ID=1\nGTR_ENABLE_WRITES=true\n')
    monkeypatch.setenv('GTR_PASSWORD', 'gtr-only')
    values = load_profiles(path)
    assert values['GTR'].email == ''
    assert values['MTR'].password.get_secret_value() == ''
    assert values['GTR'].password.get_secret_value() == 'gtr-only'
    assert not values['GTR'].enable_writes
    with path.open('a') as f:
        f.write(''.join(f'B{i}_PLATFORM_URL=https://b{i}.example\n' for i in range(3)))
    assert len(load_profiles(path)) == 5
    with path.open('a') as f:
        f.write('B4_PLATFORM_URL=https://b4.example\n')
    with pytest.raises(ValueError, match='five'):
        load_profiles(path)


def test_duplicate_profile_rejected(tmp_path):
    path = tmp_path / '.env'
    path.write_text('MTR_PLATFORM_URL=https://one.example\nGTR_PLATFORM_URL=https://one.example\n')
    with pytest.raises(ValueError, match='Duplicate'):
        load_profiles(path)


def test_simultaneous_brokers_with_same_ids_remain_isolated(settings):
    barrier = Barrier(2)
    apis = {}
    class API:
        def __init__(self, config):
            assert not config.enable_writes
            self.config, self.closed = config, False
            self.connection = SimpleNamespace(account_id=config.account_id)
            apis[config.platform_url] = self
        def login(self):
            barrier.wait(timeout=5)
        def balance(self):
            return Balance(balance='10' if 'first' in self.config.platform_url else '20', equity='5', currency='USD', token='private')
        def active_orders(self):
            return [Order(id='same-id', symbol=self.config.platform_url, side='BUY', type='LIMIT', volume='0.05', activationPrice='4300', secret='private')]
        def open_positions(self): return []
        def close(self): self.closed = True
    profiles = BrokerProfiles({name: settings.model_copy(update={'platform_url': origin, 'account_id': 'same-account'}) for name, origin in [('GTR', 'https://first.example'), ('THIRD', 'https://second.example')]}, None, api_factory=API)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda name: profiles.action(name, 'connect'), ['GTR', 'THIRD']))
    rows = profiles.snapshot()['profiles']
    assert [r['balance']['balance'] for r in rows] == ['10', '20']
    assert rows[0]['orders'][0]['symbol'] != rows[1]['orders'][0]['symbol']
    assert 'private' not in str(rows)
    profiles.action('GTR', 'disconnect')
    rows = profiles.snapshot()['profiles']
    assert 'balance' not in rows[0] and rows[1]['connection'] == 'connected'
    assert not apis['https://second.example'].closed
    apis['https://second.example'].balance = lambda: (_ for _ in ()).throw(RuntimeError('private auth error'))
    profiles.action('THIRD', 'refresh')
    assert 'balance' not in profiles.snapshot()['profiles'][1]
    assert 'private auth error' not in str(profiles.snapshot())
    profiles.close()


def test_primary_reuses_existing_owner_and_blocks_account_mismatch(settings):
    primary = SimpleNamespace(lock=RLock(), selected='other', connection='connected', api=None)
    profiles = BrokerProfiles({'MTR': settings}, primary)
    result = profiles.snapshot()['profiles'][0]
    assert result['connection'] == 'unavailable'
    profiles.action('MTR', 'refresh')
    assert 'balance' not in profiles.snapshot()['profiles'][0]
    with pytest.raises(ValueError):
        profiles.action('missing', 'connect')
    with pytest.raises(ValueError):
        profiles.action('MTR', 'trade')
    profiles.close()


def test_closed_history_uses_only_the_requested_profile(settings):
    from tests.dashboard.test_closed_history import WINDOW, broker, trade
    profiles = BrokerProfiles({'GTR': settings.model_copy(update={'account_id': '123'})}, None)
    api = broker([trade()])
    api.close = lambda: None
    profiles.entries['GTR']['api'] = api
    try:
        assert profiles.closed_history('GTR', {**WINDOW, 'account_id': '123'})['account_id'] == '123'
        with pytest.raises(ValueError):
            profiles.closed_history('GTR', {**WINDOW, 'account_id': 'other'})
    finally:
        profiles.close()


def test_login_then_select_without_env_account_keeps_profiles_separate(settings):
    from matchtrader.models.authentication import Authentication
    created = []
    class API:
        def __init__(self, config):
            self.settings, self.closed = config, False
            self.connection = SimpleNamespace(account_id='', session_expires_at=None)
            created.append(self)
        def discover_accounts(self):
            assert self.settings.account_id == ''
            return Authentication.model_validate({'token': 'private-token', 'accounts': [
                {'tradingAccountId': '1', 'offer': {'demo': True, 'secret': 'private-offer'}},
                {'tradingAccountId': '2'}]})
        def login(self): self.connection.account_id = self.settings.account_id
        def close(self): self.closed = True
        def balance(self): return Balance(balance=self.settings.account_id, equity='0', currency='USD')
        def active_orders(self): return []
        def open_positions(self): return []
    profiles = BrokerProfiles({n: settings.model_copy(update={'platform_url': f'https://{n}.example', 'account_id': ''})
                               for n in ['GTR', 'THIRD']}, None, api_factory=API)
    try:
        profiles.action('GTR', 'login')
        rows = profiles.snapshot()['profiles']
        assert rows[0]['accounts'] == [{'id': '1', 'demo': True}, {'id': '2', 'demo': False}]
        assert rows[1]['accounts'] == [] and created[0].closed
        assert 'private' not in str(rows)
        with pytest.raises(ValueError):
            profiles.action('GTR', 'select', 'unknown')
        with pytest.raises(ValueError):
            profiles.action('THIRD', 'select', '1')
        profiles.action('GTR', 'select', '1')
        first = profiles.entries['GTR']['api']
        profiles.action('THIRD', 'login')
        profiles.action('THIRD', 'select', '1')
        other = profiles.entries['THIRD']['api']
        assert first is not other
        profiles.action('GTR', 'select', '2')
        rows = profiles.snapshot()['profiles']
        assert first.closed and not other.closed
        assert rows[0]['account_id'] == '2' and rows[0]['balance']['balance'] == '2'
        assert rows[1]['account_id'] == '1' and rows[1]['balance']['balance'] == '1'
        profiles.action('GTR', 'disconnect')
        assert profiles.snapshot()['profiles'][0]['accounts'] == []
    finally:
        profiles.close()


def test_discovery_failure_clears_choices_and_closes_owner(settings):
    class API:
        closed = False
        def discover_accounts(self): raise RuntimeError('private password')
        def close(self): self.closed = True
    api = API()
    profiles = BrokerProfiles({'GTR': settings}, None, api_factory=lambda s: api)
    profiles.entries['GTR']['accounts'] = [{'id': 'old'}]
    assert not profiles.action('GTR', 'login')['completed']
    row = profiles.snapshot()['profiles'][0]
    assert api.closed and not row['accounts'] and 'private password' not in str(row)


def test_platform_login_cache_expiry_refresh_and_isolation(settings):
    import base64
    import json
    from datetime import UTC, datetime

    from matchtrader.models.authentication import Authentication
    calls = []
    expiry = [datetime.now(UTC).timestamp() + 600]
    class API:
        def __init__(self, config):
            self.config = config
            self.connection = SimpleNamespace(account_id='', session_expires_at=None)
        def discover_accounts(self):
            calls.append('login')
            part = base64.urlsafe_b64encode(json.dumps({'exp': expiry[0]}).encode()).decode().rstrip('=')
            return Authentication.model_validate({'token': f'header.{part}.signature', 'accounts': [{'tradingAccountId': '1'}]})
        def use_login(self, auth):
            calls.append('reuse')
            self.connection.account_id = self.config.account_id
        def balance(self): return Balance(balance='0', equity='0', currency='USD')
        def active_orders(self): return []
        def open_positions(self): return []
        def close(self): pass
    profiles = BrokerProfiles({'GTR': settings, 'THIRD': settings}, None, api_factory=API)
    profiles.action('GTR', 'login')
    profiles.action('GTR', 'login')
    rows = profiles.snapshot()['profiles']
    assert calls == ['login'] and rows[0]['login_status'] == 'connected'
    assert rows[1]['login_status'] == 'disconnected' and not rows[1]['accounts']
    profiles.action('GTR', 'refresh_login')
    assert calls == ['login', 'login']
    profiles.action('GTR', 'select', '1')
    assert calls == ['login', 'login', 'reuse']
    assert profiles.entries['GTR']['api'].connection.account_id == '1'
    part = base64.urlsafe_b64encode(b'{"exp":1}').decode().rstrip('=')
    profiles.entries['GTR']['authentication'] = Authentication.model_validate({'token': f'h.{part}.s'})
    row = profiles.snapshot()['profiles'][0]
    assert row['login_status'] == 'expired' and not row['accounts']
    expiry[0] = 1
    assert not profiles.action('GTR', 'refresh_login')['completed']
    assert profiles.entries['GTR']['authentication'] is None
    assert not profiles.snapshot()['profiles'][0]['accounts']
    profiles.close()


def test_primary_select_is_blocked_while_capture_runs(settings):
    primary = SimpleNamespace(lifecycle=RLock(), lock=RLock(), running=True)
    profiles = BrokerProfiles({'MTR': settings}, primary)
    profiles.entries['MTR']['accounts'] = [{'id': 'new'}]
    with pytest.raises(ValueError, match='Stop capture'):
        profiles.action('MTR', 'select', 'new')
    assert profiles.entries['MTR']['settings'].account_id == settings.account_id


def test_mixed_case_platform_labels_and_process_override(tmp_path, monkeypatch, settings):
    from matchtrader.dashboard.broker_profiles import load_profile_names
    path = tmp_path / '.env'
    path.write_text('MTR_Platform_name=Aqua funded\nGTR_platform_name=Second broker\n')
    monkeypatch.setenv('GTR_PLATFORM_NAME', 'Gooey Trade')
    names = load_profile_names(path)
    assert names == {'MTR': 'Aqua funded', 'GTR': 'Gooey Trade'}
    profiles = BrokerProfiles({'GTR': settings}, None, names=names)
    row = profiles.snapshot()['profiles'][0]
    assert row['label'] == 'Gooey Trade' and row['profile'] == 'GTR'


@pytest.mark.parametrize('fail', [False, True])
def test_primary_selection_clears_account_settings_and_never_retries_login(settings, tmp_path, fail):
    from matchtrader.dashboard.controller import DashboardController
    from matchtrader.models.account import Account
    created = []
    class API:
        def __init__(self, config):
            self.settings, self.closed = config, False
            self.connection = SimpleNamespace(account_id=config.account_id, session_expires_at=None)
            created.append(self)
        def login(self):
            if fail:
                raise RuntimeError('private login failure')
            return SimpleNamespace(tradingAccounts=[Account(tradingAccountId='456')])
        def close(self): self.closed = True
        def balance(self): return Balance(balance='0', equity='0', currency='USD')
        def active_orders(self): return []
        def open_positions(self): return []
    config = settings.model_copy(update={'system_uuid': 'original-system', 'ws_url': 'wss://original.example'})
    primary = DashboardController(config, tmp_path, api_factory=API)
    profiles = BrokerProfiles({'MTR': config}, primary)
    try:
        profiles.entries['MTR']['accounts'] = [{'id': '456'}]
        profiles.action('MTR', 'select', '456')
        assert len(created) == 1
        assert created[0].settings.system_uuid == '' and created[0].settings.ws_url == ''
        assert primary.selected == '456' and not primary.native.armed
        row = profiles.snapshot()['profiles'][0]
        assert row['account_id'] == '456'
        if fail:
            assert primary.api is None and created[0].closed and 'balance' not in row
        else:
            assert primary.api is created[0] and row['connection'] == 'connected'
    finally:
        profiles.close()
        primary.close()
