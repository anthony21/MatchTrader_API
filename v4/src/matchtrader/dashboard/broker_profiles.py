"""Up to five explicit broker identities with isolated read sessions and snapshots."""

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


class BrokerProfiles:
    def __init__(self, settings, primary, *, api_factory=MatchTraderAPI):
        self.primary, self.factory = primary, api_factory
        self.entries = {name: {'settings': value.model_copy(update={'enable_writes': False}), 'lock': RLock(), 'api': None, 'state': 'disconnected',
                               'error': '', 'data': {}, 'revision': 0} for name, value in settings.items()}

    def _entry(self, name):
        if name not in self.entries:
            raise ValueError('Unknown broker profile')
        return self.entries[name]

    def snapshot(self):
        result = []
        for name, entry in self.entries.items():
            with entry['lock']:
                settings = entry['settings']
                state, error = entry['state'], entry['error']
                if name == 'MTR':
                    with self.primary.lock:
                        state = self.primary.connection
                        if self.primary.selected != settings.account_id:
                            state, error = 'unavailable', 'Primary workspace selected a different account'
                        if state != 'connected':
                            entry['data'] = {}
                if not settings.account_id:
                    state, error = 'configuration required', f'Set {name}_ACCOUNT_ID in .env'
                result.append({'profile': name, 'broker': settings.platform_url, 'account_id': settings.account_id,
                               'connection': state, 'error': error, 'revision': entry['revision'], **entry['data']})
        return {'profiles': result, 'limit': 5}

    def action(self, name, action):
        entry = self._entry(name)
        if action not in {'connect', 'refresh', 'disconnect'}:
            raise ValueError('Unknown profile action')
        with entry['lock']:
            settings = entry['settings']
            if not settings.account_id:
                raise ValueError(f'Set {name}_ACCOUNT_ID in .env')
            try:
                if action == 'disconnect':
                    if name == 'MTR':
                        self.primary.stop()
                    elif entry['api']:
                        entry['api'].close()
                    entry.update(api=None, state='disconnected', data={}, error='')
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
                entry.update(data={}, state='error', error='Account operation failed; verify this profile configuration and connection')
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

    def close(self):
        for name, entry in self.entries.items():
            with entry['lock']:
                if name != 'MTR' and entry['api']:
                    entry['api'].close()
                entry.update(api=None, data={}, state='disconnected')
