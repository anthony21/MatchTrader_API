from pydantic import Field, SecretStr

from .base import Record


class Token(Record):
    token: SecretStr = Field(exclude=True)
