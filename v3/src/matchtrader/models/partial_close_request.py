from decimal import Decimal
from typing import Literal

from pydantic import Field

from .base import Request


class PartialCloseRequest(Request):
    positionId: str = Field(min_length=1)
    volume: Decimal = Field(gt=0)
    isMobile: bool = False
    instrument: str = Field(min_length=1)
    orderSide: Literal["BUY", "SELL"]
