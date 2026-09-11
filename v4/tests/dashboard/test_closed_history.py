from types import SimpleNamespace

import httpx
import pytest

from matchtrader import MatchTraderAPI
from matchtrader.core.errors import APIError
from matchtrader.dashboard.closed_history import read_history
from matchtrader.models.closed_trade import ClosedTrade


def trade(**changes):
    return ClosedTrade.model_validate(dict(id='p1', uid='close1', symbol='XAUUSD', side='BUY', volume='.1',
        openPrice='10', closePrice='11', openTime='2026-09-09T08:00:00Z', time='2026-09-10T08:00:00Z',
        profit='2', netProfit='1.5', stopLoss='9', takeProfit='11', privateSecret='must not leave backend', **changes))


def broker(rows):
    return SimpleNamespace(connection=SimpleNamespace(account_id='123'), closed_positions=lambda request: rows,
                           balance=lambda: SimpleNamespace(currency='USD'))


WINDOW = {'from': '2026-09-09T07:00:00Z', 'to': '2026-09-11T07:00:00Z'}


def test_history_preserves_partial_closes_deduplicates_and_filters_boundaries():
    first = trade()
    second = first.model_copy(update={'uid': 'close2', 'netProfit': first.netProfit * 0})
    excluded = first.model_copy(update={'uid': 'outside', 'time': WINDOW['to']})
    result = read_history(broker([first, first, second, excluded]), '123', WINDOW)
    assert result['summary'] == {'closed': 2, 'wins': 1, 'losses': 0, 'breakevens': 1, 'net_profit': '1.5'}
    assert all('privateSecret' not in row for row in result['operations'])
    assert result['operations'][0]['stopLoss'] == '9'
    assert read_history(broker([]), '123', WINDOW)['summary']['closed'] == 0


def test_history_rejects_wrong_account_long_range_and_conflicting_rows():
    with pytest.raises(ValueError, match='Connect'):
        read_history(broker([]), 'other', WINDOW)
    with pytest.raises(ValueError, match='93 days'):
        read_history(broker([]), '123', {'from': '2026-01-01T00:00:00Z', 'to': WINDOW['to']})
    first = trade()
    with pytest.raises(ValueError, match='conflicting'):
        read_history(broker([first, first.model_copy(update={'side': 'SELL'})]), '123', WINDOW)


def test_full_is_accepted_only_for_valid_closed_history(settings, auth):
    def transport(request):
        if request.url.path.endswith('mtr-login'):
            return httpx.Response(200, json=auth)
        return httpx.Response(200, json={'status': 'FULL', 'operations': []})
    with MatchTraderAPI(settings, transport=httpx.MockTransport(transport)) as api:
        api.login()
        assert api.closed_positions(WINDOW) == []
        with pytest.raises(APIError):
            api.active_orders()


@pytest.mark.parametrize('body', [{'status': 'PARTIAL', 'operations': []}, {'status': 'FULL'}, {'status': 'ERROR', 'operations': []}])
def test_incomplete_or_invalid_history_is_not_presented_as_complete(settings, auth, body):
    with MatchTraderAPI(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=auth if r.url.path.endswith('mtr-login') else body))) as api:
        api.login()
        with pytest.raises(APIError):
            api.closed_positions(WINDOW)
