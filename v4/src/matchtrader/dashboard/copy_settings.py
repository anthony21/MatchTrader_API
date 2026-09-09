"""Validated local copy settings; arming is intentionally never persisted."""

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..capture.route import RouteConfig


class CopySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: RouteConfig
    csv_limit: int = Field(default=1000, ge=1, le=100000)


def load_settings(path: Path):
    return CopySettings.model_validate_json(path.read_text()) if path.exists() else None


def save_settings(path: Path, value: CopySettings):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
