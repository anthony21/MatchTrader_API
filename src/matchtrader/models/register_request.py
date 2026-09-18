from pydantic import Field, SecretStr

from .base import Request


class RegisterRequest(Request):
    offerId: str = Field(min_length=1)
    email: str = Field(min_length=3)
    password: SecretStr = Field(min_length=8)
    partnerId: str = Field(min_length=1)
    name: str | None = None
    country: str | None = None
    parentTradingAccountUuid: str | None = None
    surname: str | None = None
    dateOfBirth: str | None = None
    phone: str | None = None
    city: str | None = None
    postCode: str | None = None
    address: str | None = None
    state: str | None = None
