"""One persisted Paper/Live mode for incoming bridge orders.

The route selects sources and symbol/volume mappings. Legacy source flags remain
readable for existing clients; automatic dispatch needs no second arming switch.
Restart always returns to Paper and previously recorded requests are never replayed.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .copy_settings import save_settings

SOURCES = ("P01", "X17", "MANUAL")


class SourceSwitches(BaseModel):
    model_config = ConfigDict(extra="forbid")
    P01: bool = False
    X17: bool = False
    MANUAL: bool = False


class CopyControls(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["paper", "live"] = "paper"
    sources: SourceSwitches = Field(default_factory=SourceSwitches)

    def enabled(self, source):
        """True only for one of the three governed sources when its switch is on. Any other
        attribution (R01, UNKNOWN, a typo) is never eligible, whatever the file says."""
        return source in SOURCES and bool(getattr(self.sources, source))


def load_controls(path: Path) -> CopyControls:
    """The controls as a process start sees them. Per-source switches persist as saved; the
    master mode always comes back as paper, whatever the file says, so an unattended restart
    can never resume live. Going live is a deliberate action taken in the running session,
    exactly as signal copying restarts disarmed."""
    if not path.exists():
        return CopyControls()
    saved = CopyControls.model_validate_json(path.read_text())
    return saved.model_copy(update={"mode": "paper"})


def save_controls(path: Path, value: CopyControls):
    # Same atomic write-then-replace as the route settings; a torn file must never be readable.
    save_settings(path, value)
