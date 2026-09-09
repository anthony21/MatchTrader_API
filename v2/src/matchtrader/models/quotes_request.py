from pydantic import Field

from .base import Request


class QuotesRequest(Request):
    symbols: str = Field(min_length=1)
