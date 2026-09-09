"""Native source identities are separate from destination broker identities."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CaptureEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal[1] = 1
    event_id: str = Field(min_length=1, max_length=200)
    machine: str = Field(min_length=1, max_length=100)
    connection_id: str = Field(min_length=1, max_length=200)
    account_id: str = Field(min_length=1, max_length=200)
    order_id: str = Field(default="", max_length=200)
    position_id: str = Field(default="", max_length=200)
    execution_id: str = Field(default="", max_length=200)
    request_id: str = Field(default="", max_length=200)
    emitted_at: datetime
    kind: Literal["REQUEST", "ACCEPTED", "REJECTED", "ORDER", "FILL", "POSITION", "SIGNAL", "ACCOUNT"]
    action: Literal["CREATE", "EDIT", "CANCEL", "CLOSE", "OBSERVE"] = "OBSERVE"
    source: Literal["MANUAL", "P01", "R01", "X17", "UNKNOWN"] = "UNKNOWN"
    sending_source: str = Field(default="", max_length=200)
    source_label: str = Field(default="", max_length=200)
    status: str = Field(default="", max_length=100)
    snapshot: bool = False
    symbol: str = Field(default="", max_length=100)
    side: Literal["BUY", "SELL", ""] = ""
    order_type: Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "UNKNOWN"] = "UNKNOWN"
    quantity: Decimal = Field(default=Decimal(0), ge=0)
    price: Decimal = Field(default=Decimal(0), ge=0)
    sl: Decimal = Field(default=Decimal(0), ge=0)
    tp: Decimal = Field(default=Decimal(0), ge=0)
    brackets_absolute: bool = True

    @field_validator("emitted_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone required")
        return value

    @property
    def scope(self):
        return [self.machine, self.connection_id, self.account_id]
