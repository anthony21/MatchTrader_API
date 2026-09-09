from decimal import Decimal

from .base import Record


class Quote(Record):
    symbol: str
    bid: Decimal
    ask: Decimal
    alias: str = ""
    timestampSec: int | None = None
    timestampMs: int | None = None
