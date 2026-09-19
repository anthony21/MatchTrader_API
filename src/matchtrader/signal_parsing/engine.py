"""Source-model registry and named projections; each batch item has its own result."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ValidationError

from .r01 import R01Signal
from .r01_order import r01_order_shape

Projection = Callable[[BaseModel], BaseModel | None]


@dataclass
class ParseResult:
    index: int
    status: Literal["parsed", "invalid", "unsupported"]
    signal: BaseModel | None = None
    shapes: dict[str, BaseModel] = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)

    def record(self):
        """JSON-safe output. Decimal fields use exact decimal strings."""
        return {
            "index": self.index,
            "status": self.status,
            "model": type(self.signal).__name__ if self.signal is not None else None,
            "signal": self.signal.model_dump(mode="json") if self.signal is not None else None,
            "shapes": {name: value.model_dump(mode="json") for name, value in self.shapes.items()},
            "issues": self.issues,
        }


def validation_issues(error, stage):
    return [
        {"stage": stage, "field": ".".join(map(str, item["loc"])), "message": item["msg"]}
        for item in error.errors(include_input=False, include_context=False, include_url=False)
    ]


class ParsingEngine:
    def __init__(self):
        self._sources = {}

    def register(self, source: str, model: type[BaseModel], *, shapes: dict[str, Projection]):
        if source in self._sources:
            raise ValueError(f"Parser already registered for {source}")
        self._sources[source] = (model, dict(shapes))

    def parse(self, payload) -> list[ParseResult]:
        results = []
        for index, item in enumerate(payload if isinstance(payload, list) else [payload]):
            result = ParseResult(index, "invalid")
            results.append(result)
            if not isinstance(item, dict):
                result.issues.append({"stage": "source", "field": "", "message": "Expected an event object"})
                continue
            source = item.get("source")
            registered = self._sources.get(source) if isinstance(source, str) else None
            if registered is None:
                result.status = "unsupported"
                result.issues.append({"stage": "source", "field": "source", "message": "No registered parser"})
                continue
            model, shapes = registered
            try:
                result.signal = model.model_validate(item)
            except ValidationError as error:
                result.issues.extend(validation_issues(error, "source"))
                continue
            result.status = "parsed"
            for name, build in shapes.items():
                try:
                    shape = build(result.signal)
                    if shape is not None:
                        result.shapes[name] = shape
                except ValidationError as error:
                    result.issues.extend(validation_issues(error, name))
                except ValueError as error:
                    result.issues.append({"stage": name, "field": "", "message": str(error)})
        return results

    def parse_raw(self, raw: str) -> list[ParseResult]:
        def invalid_constant(value):
            raise ValueError("Non-finite JSON number")

        try:
            payload = json.loads(raw, parse_float=Decimal, parse_constant=invalid_constant)
        except (ValueError, RecursionError):
            return [ParseResult(0, "invalid", issues=[
                {"stage": "json", "field": "", "message": "Expected valid finite JSON"}
            ])]
        return self.parse(payload)


def default_engine() -> ParsingEngine:
    engine = ParsingEngine()
    for source in ("r01Auto", "r01Local"):
        engine.register(source, R01Signal, shapes={"r01OrderShape": r01_order_shape})
    return engine
