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
