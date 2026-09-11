"""Up to five explicit broker identities with isolated read sessions and snapshots."""

import base64
import json
import os
import re
from datetime import UTC, datetime
from threading import RLock

from dotenv import dotenv_values

from ..api import MatchTraderAPI
from ..core.settings import Settings


def load_profiles(path):
    values = {**dotenv_values(path), **os.environ}
    prefixes = ['MTR', *sorted({key[:-13] for key, value in values.items()
                                if key.endswith('_PLATFORM_URL') and value and key != 'MTR_PLATFORM_URL'})]
    if len(prefixes) > 5:
        raise ValueError('Configure at most five broker profiles')
    result = {}
    identities = set()
    for prefix in prefixes:
        if not re.fullmatch(r'[A-Z][A-Z0-9]{0,15}', prefix):
            raise ValueError('Broker prefixes must use uppercase letters and digits')
        fields = {name: values[prefix + '_' + name.upper()] for name in Settings.model_fields
                  if values.get(prefix + '_' + name.upper()) not in (None, '')}
        fields['enable_writes'] = False
        settings = Settings(**fields)
        identity = (settings.platform_url, settings.broker_id, settings.email.casefold(), settings.account_id)
        if identity in identities:
            raise ValueError('Duplicate broker/login/account profile')
        identities.add(identity)
        result[prefix] = settings
    return result


def records(items, fields):
    return [{key: value for key, value in item.model_dump(mode='json').items() if key in fields} for item in items]


def load_profile_names(path):
    """Display labels accept mixed-case environment names; process values win."""
    values = {key.upper(): value for source in (dotenv_values(path), os.environ) for key, value in source.items()}
    return {key.removesuffix('_PLATFORM_NAME'): ' '.join(value.split())[:120]
            for key, value in values.items() if key.endswith('_PLATFORM_NAME') and value}


def login_expiry(authentication):
    try:
        part = authentication.token.get_secret_value().split('.')[1]
        exp = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))['exp']
        if isinstance(exp, bool) or not isinstance(exp, (float, int)):
            return None
        return datetime.fromtimestamp(exp, UTC)
    except (ValueError, KeyError, IndexError, TypeError, OverflowError, OSError):
        return None


def login_state(entry):
    if entry.get('authentication') is None:
        return 'disconnected'
    expiry = login_expiry(entry['authentication'])
    if expiry is None:
        return 'expiry unknown'
    return 'connected' if expiry > datetime.now(UTC) else 'expired'


class BrokerProfiles:
    def __init__(self, settings, primary, *, api_factory=MatchTraderAPI, names=None):
        self.primary, self.factory = primary, api_factory
        self.names = dict(names or {})
        self.entries = {name: {'settings': value.model_copy(update={'enable_writes': False}), 'lock': RLock(), 'api': None, 'state': 'disconnected',
                               'error': '', 'data': {}, 'revision': 0, 'accounts': [], 'authentication': None} for name, value in settings.items()}

    def _entry(self, name):
        if name not in self.entries:
            raise ValueError('Unknown broker profile')
        return self.entries[name]

    def snapshot(self):
        result = []
        for name, entry in self.entries.items():
            with entry['lock']:
                settings = entry['settings']
                login_status = login_state(entry)
                expiry = login_expiry(entry['authentication']) if entry['authentication'] else None
                state, error = entry['state'], entry['error']
                api = entry['api']
                if name == 'MTR':
                    with self.primary.lock:
                        api = self.primary.api
                        state = self.primary.connection
                        if self.primary.selected != settings.account_id:
                            state, error = 'unavailable', 'Primary workspace selected a different account'
                        if state != 'connected':
                            entry['data'] = {}
                if not settings.account_id and not entry['accounts']:
                    state, error = 'configuration required', error or 'Log in above to discover available trading accounts'
                result.append({'profile': name, 'label': self.names.get(name) or name,
                               'broker': settings.platform_url, 'account_id': settings.account_id,
                               'accounts': list(entry['accounts']) if login_status != 'expired' else [],
                               'login_status': login_status, 'login_expires_at': expiry.isoformat() if expiry else None,
                               'session_expires_at': (getattr(api.connection, 'session_expires_at', None)
                                                      if api and state == 'connected' else None),
                               'connection': state, 'error': error, 'revision': entry['revision'], **entry['data']})
        return {'profiles': result, 'limit': 5}

    def discover(self, name, *, force=False):
        entry = self._entry(name)
        with entry['lock']:
            if not force and login_state(entry) == 'connected':
                return {'profile': name, 'completed': True}
            candidate = None
            entry['accounts'] = []
            entry['authentication'] = None
            try:
                settings = entry['settings'].model_copy(update={'account_id': '', 'system_uuid': '',
                    'ws_url': '', 'ws_headers_json': '{}', 'ws_subprotocol': ''})
                candidate = self.factory(settings)
                auth = candidate.discover_accounts()
                found = auth.tradingAccounts or auth.accounts
                if not found:
                    selected = auth.selectedTradingAccount or auth.selectedAccount
                    found = [selected] if selected else []
                ids = [a.tradingAccountId for a in found]
                if not ids or any(not i for i in ids) or len(ids) != len(set(ids)):
                    raise ValueError('No unique accounts returned')
                # Explicit allowlist: offer data and account tokens never reach the UI.
                entry['accounts'] = [{'id': a.tradingAccountId, 'demo': a.offer.get('demo') is True}
                                     for a in found]
                entry['authentication'] = auth
                if login_state(entry) == 'expired':
                    raise ValueError('Broker returned an expired login')
                entry['error'] = ''
            except Exception:
                entry['authentication'] = None
                entry['accounts'] = []
                entry['error'] = 'Login failed; check this profile credentials and broker configuration'
            finally:
                if candidate:
                    candidate.close()
                entry['revision'] += 1
        return {'profile': name, 'completed': bool(entry['accounts'])}

    def select(self, name, account_id):
        entry = self._entry(name)
        with entry['lock']:
            if login_state(entry) == 'expired':
                self.discover(name, force=True)
            if account_id not in {a['id'] for a in entry['accounts']}:
                raise ValueError('Log in and select an account returned by this broker')
            if name == 'MTR':
                with self.primary.lifecycle, self.primary.lock:
                    if self.primary.running:
                        raise ValueError('Stop capture before switching the primary account')
                    self.primary.accounts = [{'id': a['id'], 'verified': True} for a in entry['accounts']]
                    if login_state(entry) == 'connected':
                        self.primary.connect(account_id, authentication=entry['authentication'])
                    else:
                        self.primary.connect(account_id)
            elif entry['api']:
                entry['api'].close()
                entry['api'] = None
            if account_id != entry['settings'].account_id:
                entry['settings'] = entry['settings'].model_copy(update={'account_id': account_id,
                    'system_uuid': '', 'ws_url': '', 'ws_headers_json': '{}', 'ws_subprotocol': ''})
            entry.update(data={}, error='', state='disconnected')
            return self.action(name, 'refresh' if name == 'MTR' else 'connect')

    def action(self, name, action, account_id=None):
        if action == 'login':
            return self.discover(name)
        if action == 'refresh_login':
            return self.discover(name, force=True)
        if action == 'select':
            return self.select(name, account_id)
        entry = self._entry(name)
        if action not in {'connect', 'refresh', 'disconnect'}:
            raise ValueError('Unknown profile action')
        with entry['lock']:
            settings = entry['settings']
            if not settings.account_id and action != 'disconnect':
                raise ValueError(f'Set {name}_ACCOUNT_ID in .env')
            try:
                if action == 'disconnect':
                    if name == 'MTR':
                        self.primary.stop()
                    elif entry['api']:
                        entry['api'].close()
                    entry.update(api=None, state='disconnected', data={}, error='', accounts=[], authentication=None)
                else:
                    if name == 'MTR':
                        if self.primary.selected != settings.account_id:
                            raise ValueError('Primary account changed')
                        if action == 'connect' and self.primary.api is None:
                            self.primary.connect(settings.account_id)
                        with self.primary.lock:
                            self._read(entry, self.primary.api, settings.account_id)
                    else:
                        if action == 'connect' and entry['api'] is None:
                            api = self.factory(settings)
                            try:
                                if login_state(entry) == 'connected':
                                    api.use_login(entry['authentication'])
                                else:
                                    api.login()
                                if api.connection.account_id != settings.account_id:
                                    raise ValueError('Broker selected a different account')
                            except Exception:
                                api.close()
                                raise
                            entry['api'] = api
                        self._read(entry, entry['api'], settings.account_id)
                    entry.update(state='connected', error='')
            except Exception:
                # Never retain a successful-looking snapshot after a failed refresh.
                entry.update(data={}, state='error', accounts=[], authentication=None,
                             error='Account operation failed; verify this profile configuration and connection')
                if name != 'MTR' and entry['api']:
                    entry['api'].close()
                    entry['api'] = None
            entry['revision'] += 1
        return {'profile': name, 'completed': True}

    def _read(self, entry, api, account_id):
        if api is None or api.connection.account_id != account_id:
            raise ValueError('Connect the configured account first')
        balance = api.balance()
        orders = api.active_orders()
        positions = api.open_positions()
        entry['data'] = {
            'updated_at': datetime.now(UTC).isoformat(),
            'balance': records([balance], {'balance', 'equity', 'currency', 'margin', 'freeMargin', 'profit', 'netProfit'})[0],
            'orders': records(orders, {'id', 'symbol', 'side', 'type', 'volume', 'activationPrice', 'stopLoss', 'takeProfit'}),
            'positions': records(positions, {'id', 'symbol', 'side', 'volume', 'openPrice', 'stopLoss', 'takeProfit', 'profit', 'netProfit'}),
        }

    def closed_history(self, name, payload):
        from .closed_history import read_history
        entry = self._entry(name)
        with entry['lock']:
            account_id = entry['settings'].account_id
            if payload.get('account_id') != account_id:
                raise ValueError('Selected account changed; reload closed trades')
            if name == 'MTR':
                with self.primary.lock:
                    if self.primary.selected != account_id:
                        raise ValueError('Primary account changed')
                    return read_history(self.primary.api, account_id, payload)
            return read_history(entry['api'], account_id, payload)

    def close(self):
        for name, entry in self.entries.items():
            with entry['lock']:
                if name != 'MTR' and entry['api']:
                    entry['api'].close()
                entry.update(api=None, data={}, state='disconnected', accounts=[], authentication=None)
