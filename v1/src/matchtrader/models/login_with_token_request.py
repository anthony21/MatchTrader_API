from pydantic import Field, SecretStr

from .base import Request


class LoginWithTokenRequest(Request):
    token: SecretStr = Field(min_length=1)
