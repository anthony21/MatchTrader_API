from pydantic import Field, SecretStr

from .base import Record


class Account(Record):
    tradingAccountId: str
    uuid: str = ""
    offer: dict = Field(default_factory=dict)
    tradingApiToken: SecretStr = Field(default=SecretStr(""), exclude=True)
    tradingAccountToken: dict = Field(default_factory=dict, exclude=True, repr=False)
