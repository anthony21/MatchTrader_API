from decimal import Decimal

from .base import Record


class ClosedTrade(Record):
    id: str
    symbol: str
    side: str
    volume: Decimal
    openPrice: Decimal
    closePrice: Decimal
    openTime: str
    time: str
    profit: Decimal
    netProfit: Decimal
    uid: str | None = None
    closingOrderID: str | None = None
    closeReason: str | None = None
    commission: Decimal | None = None
    swap: Decimal | None = None
