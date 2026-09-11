"""Account-scoped closed operations for an explicit bounded date interval."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ..models.closed_positions_request import ClosedPositionsRequest


def read_history(api, account_id, payload):
    request = ClosedPositionsRequest.model_validate({'from': payload.get('from'), 'to': payload.get('to')})
    if request.to - request.from_ > timedelta(days=93):
        raise ValueError('Choose a date range of at most 93 days')
    if api is None or not account_id or api.connection.account_id != account_id:
        raise ValueError('Connect the selected account before loading closed trades')
    fields = {'id', 'uid', 'closingOrderID', 'symbol', 'side', 'volume', 'openPrice', 'closePrice',
              'openTime', 'time', 'profit', 'netProfit', 'commission', 'swap', 'stopLoss', 'takeProfit', 'closeReason'}
    rows, identities = [], {}
    for record in api.closed_positions(request):
        row = {key: value for key, value in record.model_dump(mode='json').items() if key in fields}
        closed = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
        if closed.tzinfo is None:
            raise ValueError('Broker returned a close timestamp without timezone')
        if not request.from_ <= closed < request.to:
            continue
        key = row.get('uid') or (row['id'], row.get('closingOrderID'), row['time'])
        if key in identities:
            if identities[key] != row:
                raise ValueError('Broker returned conflicting close records')
            continue
        identities[key] = row
        rows.append(row)
    rows.sort(key=lambda row: datetime.fromisoformat(row['time'].replace('Z', '+00:00')), reverse=True)
    profits = [Decimal(row['netProfit']) for row in rows]
    balance = api.balance()
    return {'account_id': account_id, 'currency': balance.currency, 'from': request.from_.isoformat(),
            'to': request.to.isoformat(), 'updated_at': datetime.now(UTC).isoformat(), 'operations': rows,
            'summary': {'closed': len(rows), 'wins': sum(p > 0 for p in profits),
                        'losses': sum(p < 0 for p in profits), 'breakevens': sum(p == 0 for p in profits),
                        'net_profit': str(sum(profits, Decimal(0)))}}
