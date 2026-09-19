"""Load broker definitions from local environment prefixes, never browser credentials."""

import re
from dataclasses import dataclass, field

from ..core.settings import Settings
from .async_transport import TransportSettings


@dataclass(frozen=True)
class BrokerProfile:
    key: str
    label: str
    settings: Settings
    transport: TransportSettings = field(default_factory=TransportSettings)


def load_profiles(env):
    """MTR_BROKERS=AQUA,GTR; each key uses KEY_* Settings fields.

    With no list, MTR_* remains compatible as the DEFAULT broker.
    MTR_PRIMARY_BROKER names the MTR_* profile when a list is supplied.
    """
    keys = [key.strip() for key in (env.get("MTR_BROKERS") or "DEFAULT").split(",")]
    if len(keys) != len(set(keys)) or any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", key) for key in keys):
        raise ValueError("Broker keys must be unique uppercase identifiers")
    primary = env.get("MTR_PRIMARY_BROKER") or "DEFAULT"
    if primary in keys:
        keys = [primary, *(key for key in keys if key != primary)]
    profiles = []
    for key in keys:
        prefix = "MTR_" if key == primary else key + "_"
        fields = {
            name: env[prefix + name.upper()]
            for name in Settings.model_fields
            if env.get(prefix + name.upper()) not in (None, "")
        }
        network = {
            name: env[prefix + "HTTP_" + name.upper()]
            for name in TransportSettings.model_fields
            if env.get(prefix + "HTTP_" + name.upper()) not in (None, "")
        }
        profiles.append(
            BrokerProfile(
                key, env.get(key + "_LABEL") or key, Settings(**fields), TransportSettings(**network)
            )
        )
    return profiles
