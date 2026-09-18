from typing import Literal

from pydantic import Field

from .base import Request


class CancelPendingOrderRequest(Request):
    instrument: str = Field(min_length=1)
    id: str = Field(min_length=1)
    orderSide: Literal["BUY", "SELL"]
    type: Literal["LIMIT", "STOP"]
    isMobile: bool = False
