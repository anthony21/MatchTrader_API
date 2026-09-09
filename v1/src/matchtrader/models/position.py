from decimal import Decimal

from pydantic import Field

from .base import Record


class Position(Record):
    id: str
    symbol: str
    side: str
    volume: Decimal
    openPrice: Decimal
    openTime: str | None = None
    openTimeMillis: int | None = None
    stopLoss: Decimal | None = None
    takeProfit: Decimal | None = None
    trailingDistance: Decimal | None = None
    profit: Decimal | None = None
    netProfit: Decimal | None = None
    positions: list["Position"] = Field(default_factory=list)
