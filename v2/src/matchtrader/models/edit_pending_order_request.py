from decimal import Decimal
from typing import Literal

from pydantic import Field

from .base import Request


class EditPendingOrderRequest(Request):
    instrument: str = Field(min_length=1)
    id: str = Field(min_length=1)
    orderSide: Literal["BUY", "SELL"]
    type: Literal["LIMIT", "STOP"]
    volume: Decimal = Field(gt=0)
    slPrice: Decimal = Field(default=Decimal(0), ge=0)
    tpPrice: Decimal = Field(default=Decimal(0), ge=0)
    priceOrder: Decimal = Field(gt=0)
    isMobile: bool = False
