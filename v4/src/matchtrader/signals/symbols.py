"""The symbol map: incoming symbol -> destination symbol, plus the size and order handling for it.

A plain key-value table the engine looks up. It is not part of the lane settings and is not
re-declared when they are saved; it lives in its own file so it can later be replaced from an
external source such as PAMM.
"""

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class SymbolMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    destination: str = Field(min_length=1, max_length=100)
    lots: Decimal = Field(gt=0)
    # SOURCE: the sender's own type. ENTRY: pending at the logged entry, type from the sender or
    # else from the destination quote. MARKET/LIMIT/STOP: always that type.
    order_type: Literal["MARKET", "LIMIT", "STOP", "SOURCE", "ENTRY"] = "SOURCE"
    # Minimum box (take-profit to stop-loss distance) in this instrument's price units. An intent
    # with a tighter box is refused: tight boxes sit inside the instrument's noise and spread, so
    # they stop out almost instantly. 0 disables the filter (the default).
    min_box: Decimal = Field(default=Decimal(0), ge=0)


class SymbolMapStore:
    """One symbol map shared by every lane: loaded from one file, replaced through one call."""

    def __init__(self, path):
        self.path = Path(path)
        self.map = SymbolMap.load(self.path)

    def replace(self, symbols):
        self.map = symbols
        symbols.save(self.path)


class SymbolMap(RootModel[dict[str, SymbolMapping]]):
    def lookup(self, symbol) -> SymbolMapping | None:
        return self.root.get(symbol)

    def __len__(self):
        return len(self.root)

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else cls({})

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(self.model_dump(mode="json"), indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
