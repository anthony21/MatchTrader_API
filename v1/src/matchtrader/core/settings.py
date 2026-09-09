"""Explicit .env loading; importing the package never reads credentials."""

import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    platform_url: str
    email: str = Field(default="", repr=False)
    password: SecretStr = SecretStr("")
    broker_id: str = ""
    account_id: str = ""
    trading_url: str = ""
    system_uuid: str = ""
    cookie_mode: Literal["session", "account"] = "session"
    session_renewal: Literal["refresh", "login"] = "refresh"
    timeout_seconds: float = Field(default=20, gt=0, le=300)
    requests_per_minute: int = Field(default=450, ge=1, le=500)
    enable_writes: bool = False
    ws_url: str = ""
    ws_subprotocol: str = ""
    ws_headers_json: SecretStr = SecretStr("{}")
    ws_ping_interval: float = Field(default=20, gt=0)
    ws_max_size: int = Field(default=1048576, ge=1024, le=16777216)

    @field_validator("platform_url", "trading_url", "ws_url")
    @classmethod
    def secure_origin(cls, value: str, info):
        if not value and info.field_name != "platform_url":
            return value
        u = urlsplit(value)
        scheme = "wss" if info.field_name == "ws_url" else "https"
        if u.scheme != scheme or not u.hostname or u.username or u.password or u.fragment:
            raise ValueError(f"Use a {scheme} URL without embedded credentials or fragment")
        if info.field_name != "ws_url" and (u.path not in ("", "/") or u.query):
            raise ValueError("REST URLs must be origins, without paths or query strings")
        return value.rstrip("/")

    @field_validator("system_uuid")
    @classmethod
    def safe_system(cls, value: str):
        if value and not all(c.isalnum() or c in "-_" for c in value):
            raise ValueError("Invalid system identifier")
        return value

    @field_validator("ws_headers_json")
    @classmethod
    def headers_object(cls, value: SecretStr):
        try:
            obj = json.loads(value.get_secret_value())
        except ValueError:
            raise ValueError("WebSocket headers must be a JSON object") from None
        if not isinstance(obj, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or "\r" in k + v or "\n" in k + v
            for k, v in obj.items()
        ):
            raise ValueError("WebSocket headers must map names to single-line strings")
        return value

    @classmethod
    def from_env(cls, path: str | Path = ".env"):
        values = {**dotenv_values(path), **os.environ}
        fields = {}
        for name in cls.model_fields:
            value = values.get("MTR_" + name.upper())
            if value is not None and value != "":
                fields[name] = value
        return cls(**fields)
