"""An R01 order projection and its explicit conversion to existing SDK requests."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models.create_pending_order_request import CreatePendingOrderRequest
from ..models.open_position_request import OpenPositionRequest
from .r01 import R01Signal


class R01OrderShape(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    instrument: str = Field(min_length=1)
    orderSide: Literal["BUY", "SELL"]
    type: Literal["LIMIT", "STOP", "MARKET"]
    price: Decimal | None = Field(default=None, gt=0)
    slPrice: Decimal = Field(ge=0)
    tpPrice: Decimal = Field(ge=0)
    isMobile: bool = False

    @model_validator(mode="after")
    def pending_price(self):
        if self.type != "MARKET" and self.price is None:
            raise ValueError("Pending orders require a positive price")
        return self

    def to_request(self, *, volume: Decimal, instrument: str):
        """Supply destination sizing/symbol explicitly; return a validated SDK model."""
        fields = self.model_dump(exclude={"instrument", "type", "price"})
        fields.update(instrument=instrument, volume=volume)
        if self.type == "MARKET":
            return OpenPositionRequest(**fields)
        return CreatePendingOrderRequest(**fields, type=self.type, price=self.price)


def r01_order_shape(signal: R01Signal) -> R01OrderShape | None:
    if signal.source != "r01Auto" or signal.kind != "intent":
        return None
    side = {"long": "BUY", "short": "SELL"}.get(signal.side.lower())
    if side is None:
        raise ValueError("Order intent side must be long or short")
    return R01OrderShape(
        instrument=signal.symbol,
        orderSide=side,
        type=signal.orderType.upper(),
        price=None if signal.orderType.upper() == "MARKET" else signal.entry,
        slPrice=signal.stopLoss,
        tpPrice=signal.takeProfit,
    )
