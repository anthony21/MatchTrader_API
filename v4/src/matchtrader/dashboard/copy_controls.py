"""Persisted copy controls: one Paper/Live master switch plus a per-source enable.

The default is the safe state - paper mode with every source off - and it is what a
missing or unreadable file resolves to. Enabling a source only makes that source's
captured trades *eligible*, visible as candidates; it never sends anything. A trade
reaches the broker solely through an explicit send action, and only while the master
switch is on live. Paper records the exact broker request and sends nothing.
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
    return CopyControls.model_validate_json(path.read_text()) if path.exists() else CopyControls()


def save_controls(path: Path, value: CopyControls):
    # Same atomic write-then-replace as the route settings; a torn file must never be readable.
    save_settings(path, value)
