from decimal import Decimal

from .base import Record


class Balance(Record):
    balance: Decimal
    equity: Decimal
    currency: str
    margin: Decimal | None = None
    freeMargin: Decimal | None = None
    marginLevel: Decimal | None = None
    credit: Decimal | None = None
    profit: Decimal | None = None
    netProfit: Decimal | None = None
