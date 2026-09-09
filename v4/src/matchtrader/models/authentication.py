from pydantic import Field, SecretStr

from .account import Account
from .base import Record


class Authentication(Record):
    token: SecretStr = Field(exclude=True)
    tradingAccounts: list[Account] = Field(default_factory=list)
    accounts: list[Account] = Field(default_factory=list)
    selectedTradingAccount: Account | None = None
    selectedAccount: Account | None = None
