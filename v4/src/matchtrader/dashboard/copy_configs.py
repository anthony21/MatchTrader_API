"""Saved copy configurations: the wire-driven per-strategy copy model.

Each configuration copies the signals of one strategy, identified by the machineId it sends on the
wire, to one broker account, with its own sizing, grades and its own Paper/Live and On/Off state.
There is no global copy switch: only enabled configurations copy, each independently. The list is
a plain key-value table persisted to its own file, looked up for every incoming wire signal.
"""

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class CopyConfig(BaseModel):
    """One named configuration. Exposes the attributes the signal engine reads from a "lane"
    (machine_id, source, additional_sources, connection_name, destination_account, accepted_grades,
    retract_on_downgrade, sizing, sizing_value) plus its own identity and live state."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    # The source is the strategy's wire machineId; source is its signal family (r01Auto/chain/panel).
    machine_id: str = Field(min_length=1, max_length=100)
    source: str = Field(default="r01Auto", min_length=1, max_length=100)
    connection_name: str = Field(default="", max_length=200)
    additional_sources: list[Literal["chain", "panel"]] = Field(default_factory=list)
    x17_only: bool = False
    # Destination: which broker profile, then the account under it.
    destination_broker: str = Field(default="", max_length=64)
    destination_account: str = Field(min_length=1, max_length=200)
    accepted_grades: list[Literal["PRIME", "STRONG", "FAIR", "POOR", "WEAK", "AVOID"]] = Field(default_factory=list)
    retract_on_downgrade: bool = True
    sizing: Literal["lots", "dollar", "percent"] = "lots"
    sizing_value: Decimal | None = Field(default=None, gt=0)
    mode: Literal["paper", "live"] = "paper"
    enabled: bool = False

    def matches(self, machine_id, source):
        """True when a wire signal with this machineId and source belongs to this configuration."""
        return machine_id == self.machine_id and source in {self.source, *self.additional_sources}


class CopyConfigList(RootModel[list[CopyConfig]]):
    def ids(self):
        return {c.id for c in self.root}


class CopyConfigStore:
    """The saved configurations, loaded from one file and changed through explicit calls. Ids are
    unique; a config keeps its own mode and enabled flag so nothing global governs copying."""

    def __init__(self, path):
        self.path = Path(path)
        self.configs = self._load()

    def _load(self):
        if self.path.exists():
            return {c.id: c for c in CopyConfigList.model_validate_json(self.path.read_text(encoding="utf-8")).root}
        return {}

    def list(self):
        return list(self.configs.values())

    def get(self, config_id):
        return self.configs.get(config_id)

    def upsert(self, config: CopyConfig):
        if len(self.configs) >= 25 and config.id not in self.configs:
            raise ValueError("Configure at most 25 copy configurations")
        self.configs[config.id] = config
        self._save()
        return config

    def delete(self, config_id):
        if self.configs.pop(config_id, None) is None:
            raise ValueError("Unknown copy configuration")
        self._save()

    def set_state(self, config_id, *, mode=None, enabled=None):
        config = self.configs.get(config_id)
        if config is None:
            raise ValueError("Unknown copy configuration")
        update = {}
        if mode is not None:
            update["mode"] = mode
        if enabled is not None:
            update["enabled"] = enabled
        config = config.model_copy(update=update)
        self.configs[config_id] = config
        self._save()
        return config

    def matching(self, machine_id, source):
        """Every enabled configuration a wire signal with this machineId and source belongs to."""
        return [c for c in self.configs.values() if c.enabled and c.matches(machine_id, source)]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = CopyConfigList(list(self.configs.values())).model_dump(mode="json")
        descriptor, name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
