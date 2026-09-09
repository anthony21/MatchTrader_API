from decimal import Decimal

from .base import Record


class Order(Record):
    id: str
    symbol: str
    side: str
    type: str
    volume: Decimal
    activationPrice: Decimal
    stopLoss: Decimal | None = None
    takeProfit: Decimal | None = None
    creationTime: str | None = None
