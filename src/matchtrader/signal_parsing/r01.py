"""The complete R01 wire event, preserving sender names and values."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class R01Signal(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="allow", allow_inf_nan=False, hide_input_in_errors=True
    )

    mode: str
    source: Literal["r01Auto", "r01Local"]
    kind: str = Field(min_length=1)
    label: str
    brokerOrderId: str
    brokerPositionId: str
    rangeKind: str
    wasBeyond: bool
    wallId: str
    boxInstanceId: str
    symbol: str
    side: str
    entry: Decimal
    stopLoss: Decimal
    takeProfit: Decimal
    ladderGrade: str
    stamp: Decimal
    l2Class: str
    l2Word: str
    l2DbandDigit: int
    l2BirthRank: int
    l2ChurnBand: str
    l2PosInWin: bool
    tapHash: str
    clientEventId: str = Field(min_length=1)
    refClientEventId: str
    tier: str
    cell: str
    rfx: str
    inverted: bool
    orderType: str
    volume: Decimal
    grade: str  # Preserved source data; projections use ladderGrade.
    ladderArm: str
    detail: str
    dryRun: bool
    machineId: str = Field(min_length=1)
    robotName: str
    accountId: str
    connectionName: str
    timestampUtc: str
    sequence: int
    instrument: dict[str, Any] | None

    @field_validator("entry", "stopLoss", "takeProfit", "stamp", "volume", mode="before")
    @classmethod
    def decimal_number(cls, value):
        if type(value) not in (int, float, Decimal):
            raise ValueError("Expected a JSON number")
        return Decimal(str(value))

    @field_validator("timestampUtc")
    @classmethod
    def timestamp_with_timezone(cls, value):
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")
        # Keep the original string, including the sender's sub-microsecond digits.
        return value
