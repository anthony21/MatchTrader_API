"""Response objects preserve unknown broker fields; requests reject misspellings."""

import json
import math

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, hide_input_in_errors=True)


class Request(Record):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        hide_input_in_errors=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def valid_range(self):
        if hasattr(self, "from_") and self.from_ >= self.to:
            raise ValueError("from must precede to")
        return self

    def wire(self):
        # Pydantic serializes Decimal as strings; the API requires JSON numbers in most requests.
        from decimal import Decimal

        def convert(x):
            if isinstance(x, SecretStr):
                return x.get_secret_value()
            if isinstance(x, Decimal):
                number = float(x)
                if not math.isfinite(number):
                    raise ValueError("Request number exceeds JSON floating-point range")
                return number
            if isinstance(x, dict):
                return {k: convert(v) for k, v in x.items()}
            if isinstance(x, list):
                return [convert(v) for v in x]
            return x

        body = convert(self.model_dump(by_alias=True, exclude_none=True))
        # Datetimes are serialized by Pydantic; preserve numeric Decimal wire types.
        return json.loads(json.dumps(body, default=lambda v: v.isoformat()))
