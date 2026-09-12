"""Explicit source selection, symbol and quantity conversion; no implicit routes."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SymbolRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    destination: str = Field(min_length=1)
    quantity_multiplier: Decimal = Field(gt=0)
    max_lots: Decimal = Field(gt=0)
    fixed_lots: Decimal | None = Field(default=None, gt=0)
    # Prices are copied only for explicitly confirmed equivalent instruments.
    same_price_scale: Literal[True]


class RouteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine: str = Field(min_length=1)
    connection_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    destination_account: str = Field(min_length=1)
    sources: list[Literal["MANUAL", "P01", "R01", "X17", "UNKNOWN"]] = Field(min_length=1)
    symbols: dict[str, SymbolRoute] = Field(min_length=1)
    exclusive_destination: Literal[True]
    legacy_route_disabled: Literal[True]

    def match(self, event):
        if event.scope != [self.machine, self.connection_id, self.account_id]:
            raise ValueError("Source connection/account does not match configured route")
        if event.source not in self.sources:
            raise ValueError("Source attribution is not enabled for this route")
        if event.symbol not in self.symbols:
            raise ValueError("No explicit symbol/quantity mapping")
        return self.symbols[event.symbol]
