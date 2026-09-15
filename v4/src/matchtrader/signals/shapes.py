"""One base shape every sender shares; one subclass per sender for what differs.

The base carries what every intent needs to become an order: identity (machine, source, client
event id, label), lifecycle kind, timestamp, symbol, side, and the three prices. Each subclass
adds what only that sender knows and states how its labels and attribution are recognised.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

SIDES = {"long": "BUY", "short": "SELL", "buy": "BUY", "sell": "SELL", "0": "BUY", "1": "SELL"}


class BaseSignal(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    clientEventId: str = Field(min_length=1, max_length=200)
    machineId: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=100)
    connectionName: str = Field(default="", max_length=200)
    accountId: str = Field(default="", max_length=200)
    kind: str = Field(min_length=1, max_length=100)
    label: str = Field(default="", max_length=200)
    timestampUtc: datetime
    symbol: str = Field(default="", max_length=100)
    side: str = Field(default="", max_length=20)
    entry: Decimal = Field(default=Decimal(0), ge=0)
    stopLoss: Decimal = Field(default=Decimal(0), ge=0)
    takeProfit: Decimal = Field(default=Decimal(0), ge=0)
    # The sender's own order type, when it states one: MARKET, LIMIT or STOP.
    copyOrderType: Literal["", "MARKET", "LIMIT", "STOP"] = Field(
        default="", validation_alias=AliasChoices("copyOrderType", "orderType"))

    @field_validator("copyOrderType", mode="before")
    @classmethod
    def normalize_type(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator("side", mode="before")
    @classmethod
    def normalize_side(cls, value):
        return SIDES.get(str(value).lower(), str(value)) if value is not None else ""

    @field_validator("timestampUtc")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamp must include a timezone")
        return value.astimezone(UTC)

    @property
    def scope(self):
        """The identity a cancel must share with its intent: who sent it, from where, for what."""
        return (self.machineId, self.source, self.accountId, self.connectionName, self.symbol, self.label)

    def check_attribution(self, lane):
        """Sender-specific proof that this intent is what the lane expects. Base: nothing extra."""


class P01Signal(BaseSignal):
    """Manual boxes from the P01 RR tool, from its local log or its structured panel signal.

    Labels are the tool's own lifecycle ids: P01RR_HHmmss_n for chart-origin boxes, or
    L:<edge>@<wall>@<bar> (M: for mirrored levels) on charts with a mint file.
    """

    LABEL: ClassVar[re.Pattern] = re.compile(r"^(P01RR_\d+_\d+|[LM]:(?:low|high|beyond)@\S+)$")
    origin: str = Field(default="", max_length=40)   # chart / level, when the tool states it

    def check_attribution(self, lane):
        if self.source == "panel" and not self.label.startswith("P01RR_"):
            raise ValueError("Panel intent is not identified as manual P01")
        if self.source == "P01_LOG" and not self.LABEL.match(self.label):
            raise ValueError("P01 log intent does not carry a recognised lifecycle label")


class ChainSignal(BaseSignal):
    """Level intents published by the X17 spine through the relay; `detail` names the publisher."""

    detail: str = Field(default="", max_length=400)

    @property
    def from_x17(self):
        return self.detail.lower().startswith("x17-spine ")

    def check_attribution(self, lane):
        if getattr(lane, "x17_only", False) and not self.from_x17:
            raise ValueError("Chain intent is not identified as X17")


class R01Signal(BaseSignal):
    """R01 strategy intents: the ledger grade and its context ride along, for gating and records.

    R01 states the order type in its detail text rather than as a field.
    """

    DETAIL_TYPES: ClassVar[dict] = {
        "resting limit at range edge": "LIMIT",
        "resting stop at beyond edge": "STOP",
        "resting stop-limit at beyond edge, limit at trigger": "STOP",
    }
    grade: str = Field(default="", max_length=40)
    stamp: str = Field(default="", max_length=20)
    rfx: str = Field(default="", max_length=40)
    arm: str = Field(default="", max_length=120)
    detail: str = Field(default="", max_length=400)

    @property
    def order_type(self):
        return self.copyOrderType or self.DETAIL_TYPES.get(self.detail, "")


SOURCES = {"P01_LOG": P01Signal, "panel": P01Signal, "chain": ChainSignal,
           "R01": R01Signal, "r01": R01Signal, "r01Auto": R01Signal}


def parse_signal(raw) -> BaseSignal:
    """The subclass for the sender named in `source`; an unknown sender gets the base shape."""
    shape = SOURCES.get(str(raw.get("source", "")), BaseSignal)
    return shape.model_validate(raw)
