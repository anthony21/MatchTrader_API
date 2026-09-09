from pydantic import AliasChoices, Field, SecretStr

from .base import Request


class LoginRequest(Request):
    email: str = Field(min_length=3, validation_alias=AliasChoices("email", "username"))
    password: SecretStr = Field(min_length=1)
    brokerId: str = Field(min_length=1, validation_alias=AliasChoices("brokerId", "brokerid"))
