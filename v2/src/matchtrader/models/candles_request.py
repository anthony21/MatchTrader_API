from pydantic import AwareDatetime, Field

from .base import Request


class CandlesRequest(Request):
    symbol: str = Field(min_length=1)
    interval: str = Field(min_length=1)
    from_: AwareDatetime = Field(alias="from")
    to: AwareDatetime
