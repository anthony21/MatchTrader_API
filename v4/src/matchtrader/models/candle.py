from decimal import Decimal

from .base import Record


class Candle(Record):
    time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
