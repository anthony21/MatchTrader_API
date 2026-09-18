from decimal import Decimal
from typing import Literal

from pydantic import Field

from .base import Request


class CreatePendingOrderRequest(Request):
    instrument: str = Field(min_length=1)
    orderSide: Literal["BUY", "SELL"]
    volume: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    type: Literal["LIMIT", "STOP"]
    slPrice: Decimal = Field(default=Decimal(0), ge=0)
    tpPrice: Decimal = Field(default=Decimal(0), ge=0)
    isMobile: bool = False
