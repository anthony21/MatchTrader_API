from decimal import Decimal

from .base import Record


class Instrument(Record):
    symbol: str
    alias: str = ""
    pricePrecision: int | None = None
    volumePrecision: int | None = None
    volumeMin: Decimal | None = None
    volumeMax: Decimal | None = None
    volumeStep: Decimal | None = None
    contractSize: Decimal | None = None
    stopsLevel: Decimal | None = None
    freezeLevel: Decimal | None = None
