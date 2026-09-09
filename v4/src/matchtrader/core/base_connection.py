"""Singleton registry with one leased transport per broker/login/account identity."""

from threading import RLock
from typing import ClassVar

from .errors import ConfigurationError, ConnectionClosedError


class BaseConnection:
    _registry: ClassVar[dict] = {}
    _registry_lock = RLock()
    _creation_key = object()

    def __init__(self, settings, *, _key=None):
        if _key is not self._creation_key:
            raise ConfigurationError("Use acquire() to obtain the shared connection")
        self.settings = settings
        self.closed = False
        self._leases = 1
        self._registry_key = type(self).identity(settings)

    @classmethod
    def identity(cls, settings):
        return (cls, settings.platform_url, settings.broker_id, settings.email, settings.account_id)

    @classmethod
    def acquire(cls, settings, **kwargs):
        with cls._registry_lock:
            key = cls.identity(settings)
            existing = cls._registry.get(key)
            if existing is not None:
                if existing.settings != settings:
                    raise ConfigurationError("Close this account's connection before changing its settings")
                if kwargs:
                    raise ConfigurationError("Cannot replace dependencies of an active singleton")
                existing._leases += 1
                return existing
            instance = cls(settings, _key=cls._creation_key, **kwargs)
            cls._registry[key] = instance
            return instance

    def ensure_open(self):
        if self.closed:
            raise ConnectionClosedError("Connection is closed")

    def release(self):
        with self._registry_lock:
            if self.closed:
                return
            self._leases -= 1
            if self._leases == 0:
                self.closed = True
                try:
                    self._shutdown()
                finally:
                    self._registry.pop(self._registry_key, None)

    def _shutdown(self):
        raise NotImplementedError
