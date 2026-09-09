"""Local shadow ingress; this package never submits broker orders."""

from .api import ShadowBridge
from .event import OrderEvent

__all__ = ["OrderEvent", "ShadowBridge"]
