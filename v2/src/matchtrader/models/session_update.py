"""Optional JSON refresh body; credentials stay excluded from serialization."""

from pydantic import Field, SecretStr

from .authentication import Authentication


class SessionUpdate(Authentication):
    token: SecretStr | None = Field(default=None, exclude=True)
