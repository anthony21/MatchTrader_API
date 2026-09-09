from pydantic import AwareDatetime, Field

from .base import Request


class ClosedPositionsRequest(Request):
    from_: AwareDatetime = Field(alias="from")
    to: AwareDatetime
