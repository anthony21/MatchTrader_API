from decimal import Decimal
from typing import Literal

from pydantic import Field

from .base import Request


class ClosePositionRequest(Request):
    positionId: str = Field(min_length=1)
    instrument: str = Field(min_length=1)
    orderSide: Literal["BUY", "SELL"]
    volume: Decimal = Field(gt=0)

    def wire(self):
        data = super().wire()
        data["volume"] = str(self.volume)
        return data
