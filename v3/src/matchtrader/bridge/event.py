"""Versioned sender contract, distinct from R01's incomplete CSV observations."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")]
Positive = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class OrderEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal[1] = 1
    source_machine: Identifier
    strategy_instance: Identifier
    event_id: Identifier
    source_order_id: Identifier
    revision: int = Field(ge=1, strict=True)
    emitted_at: AwareDatetime
    account_id: Identifier
    action: Literal["CREATE", "EDIT", "CANCEL"]
    instrument: str = Field(min_length=1, max_length=64, pattern=r"^\S+$")
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]
    volume_lots: Positive | None = None
    price: Positive | None = None
    trigger_price: Positive | None = None
    # Explicit zero removes a bracket; omission is not silently interpreted as zero.
    sl_price: Nonnegative | None = None
    tp_price: Nonnegative | None = None

    @model_validator(mode="after")
    def complete_state(self):
        if self.action != "CANCEL":
            if self.volume_lots is None or self.sl_price is None or self.tp_price is None:
                raise ValueError("CREATE/EDIT require lot size and explicit SL/TP (zero means unset)")
            if self.order_type != "MARKET" and self.price is None:
                raise ValueError("Pending orders require price")
        if self.order_type == "STOP_LIMIT" and self.trigger_price is None:
            raise ValueError("STOP_LIMIT requires a separate trigger price")
        if self.order_type != "STOP_LIMIT" and self.trigger_price is not None:
            raise ValueError("Separate trigger price is only valid for STOP_LIMIT")
        if self.order_type == "MARKET" and self.price is not None:
            raise ValueError("MARKET must not carry a pending entry price")
        return self

    def order_key(self):
        return self.source_machine, self.strategy_instance, self.account_id, self.source_order_id
