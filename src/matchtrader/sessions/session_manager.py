"""One independent, memory-only authentication owner per registered broker."""

import asyncio
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from threading import Event, RLock, Thread
from typing import Any, Protocol

from ..core.errors import AuthenticationError


@dataclass(repr=False, frozen=True)
class SessionData:
    expires_at: float
    accounts: tuple[str, ...]
    payload: Any = field(repr=False)


class BrokerAdapter(Protocol):
    identity: tuple

    def login(self) -> SessionData: ...
    def refresh(self, previous: SessionData) -> SessionData: ...
    def execute(self, session: SessionData, account_id: str, operation: str, *args, **kwargs): ...


@dataclass(repr=False)
class BrokerSession:
    key: str
    label: str
    adapter: BrokerAdapter
    lock: Any = field(default_factory=RLock)
    lifecycle: Any = field(default_factory=RLock)
    wake: Event = field(default_factory=Event)
    data: SessionData | None = None
    connected: bool = False
    healthy: bool = False
    next_refresh: float | None = None
    failures: int = 0
    message: str = "Disconnected"
    worker: Thread | None = None
    executor: Any = None
    inflight: int = 0
    generation: int = 0
    idle: Event = field(default_factory=Event)


class SessionManager:
    """Registry of token containers; no sockets or SDK clients are retained here.

    Per-broker locks publish complete token snapshots atomically. Workers are
    independent, so a slow broker cannot delay another broker's renewal.
    """

    def __init__(self, *, clock=time.time, automatic=True):
        self._clock = clock
        self._automatic = automatic
        self._lock = RLock()
        self._sessions = {}
        self._closed = False
        self._closing = False

    def register(self, key, label, adapter):
        with self._lock:
            if self._closed or self._closing:
                raise RuntimeError("Session manager is closed")
            if not key or key in self._sessions:
                raise ValueError("Broker key must be unique")
            if any(s.adapter.identity == adapter.identity for s in self._sessions.values()):
                raise ValueError("This broker already has a session owner")
            session = BrokerSession(key, label, adapter)
            config = getattr(adapter, "transport_settings", None)
            session.executor = ThreadPoolExecutor(
                max_workers=(config.expected_concurrency if config else 16) + 2,
                thread_name_prefix=f"broker-sdk-{key}",
            )
            session.idle.set()
            self._sessions[key] = session

    def _get(self, key):
        with self._lock:
            if self._closed:
                raise RuntimeError("Session manager is closed")
            if key not in self._sessions:
                raise ValueError("Unknown broker")
            return self._sessions[key]

    def _adopt(self, session, data):
        if not math.isfinite(data.expires_at) or data.expires_at <= self._clock() + 180:
            raise AuthenticationError("Broker token has less than three minutes remaining")
        if (
            not data.accounts
            or len(set(data.accounts)) != len(data.accounts)
            or any(not isinstance(account, str) or not account.strip() for account in data.accounts)
        ):
            raise AuthenticationError("Broker did not supply unique account identities")
        session.data = data
        session.healthy = True
        session.failures = 0
        session.next_refresh = data.expires_at - 180
        session.message = "Connected; automatic renewal scheduled"

    def connect(self, key):
        session = self._get(key)
        with session.lifecycle:
            with self._lock:
                if self._closed or self._closing:
                    raise RuntimeError("Session manager is closed")
            return self._connect(session)

    def _connect(self, session):
        with session.lock:
            if session.connected:
                if not session.healthy:
                    raise AuthenticationError("Broker renewal is retrying")
                return session.data
            try:
                self._adopt(session, session.adapter.login())
            except Exception:
                session.message = "Login failed; check broker credentials and configuration"
                raise AuthenticationError(session.message) from None
            session.connected = True
            session.generation += 1
            session.wake.clear()
            if self._automatic and (session.worker is None or not session.worker.is_alive()):
                session.worker = Thread(
                    target=self._watch, args=(session,), name=f"broker-session-{session.key}", daemon=True
                )
                session.worker.start()
            return session.data

    def _refresh(self, session):
        try:
            renewed = session.adapter.refresh(session.data)
            if renewed.expires_at <= session.data.expires_at:
                raise AuthenticationError("Renewal did not advance token expiry")
            self._adopt(session, renewed)
        except Exception:
            session.healthy = False
            session.failures += 1
            session.next_refresh = self._clock() + min(30, 2 ** min(session.failures, 5))
            session.message = "Renewal failed; retry scheduled; broker requests paused"
            return False
        return True

    def refresh(self, key):
        session = self._get(key)
        with session.lock:
            if not session.connected:
                raise AuthenticationError("Connect before refreshing")
            success = self._refresh(session)
            session.wake.set()
            if not success:
                raise AuthenticationError(session.message)
            return session.data

    def _watch(self, session):
        while True:
            with session.lock:
                if not session.connected:
                    return
                session.wake.clear()
                delay = max(0, session.next_refresh - self._clock())
            if session.wake.wait(min(delay, 1)):
                continue
            with session.lock:
                if not session.connected:
                    return
                if self._clock() >= session.next_refresh:
                    self._refresh(session)

    def renew_due(self):
        """Deterministic scheduler tick for offline verification or an external scheduler."""
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            with session.lock:
                if session.connected and self._clock() >= session.next_refresh:
                    self._refresh(session)

    def execute(self, key, account_id, operation, *args, _generation=None, **kwargs):
        session = self._get(key)
        with session.lock:
            if _generation is not None and _generation != session.generation:
                raise AuthenticationError("Request belongs to a disconnected session")
            if not session.connected or not session.healthy or self._clock() >= session.data.expires_at:
                raise AuthenticationError("Broker session is unavailable; requests are paused")
            if account_id not in session.data.accounts:
                raise AuthenticationError("Account is not part of this broker session")
            snapshot = session.data
            session.inflight += 1
            session.idle.clear()
        # A slow broker request must not delay its renewal timer. Every request
        # gets an immutable snapshot and its own short-lived SDK view.
        try:
            return session.adapter.execute(snapshot, account_id, operation, *args, **kwargs)
        except AuthenticationError:
            with session.lock:
                if session.connected and session.data is snapshot:
                    session.healthy = False
                    session.next_refresh = self._clock()
                    session.message = "Broker rejected authentication; renewal scheduled"
                    session.wake.set()
            # Never replay a trade after an authentication failure.
            raise
        finally:
            with session.lock:
                session.inflight -= 1
                if not session.inflight:
                    session.idle.set()

    def disconnect(self, key):
        session = self._get(key)
        with session.lifecycle:
            self._disconnect(session)

    async def aexecute(self, key, account_id, operation, *args, **kwargs):
        session = self._get(key)
        with session.lock:
            if not session.connected:
                raise AuthenticationError("Broker session is disconnected")
            pending = session.executor.submit(
                partial(
                    self.execute, key, account_id, operation, *args, _generation=session.generation, **kwargs
                )
            )
        # Only the immutable SDK's synchronous validation/dispatch runs in workers.
        # Actual socket I/O multiplexes asynchronously on the broker's pool loop.
        return await asyncio.wrap_future(pending)

    def _disconnect(self, session):
        with session.lock:
            session.connected = session.healthy = False
            session.generation += 1
            session.data = None
            session.next_refresh = None
            session.message = "Disconnected"
            session.wake.set()
        # Join outside the broker lock; reconnect cannot inherit a dying worker.
        if session.worker:
            session.worker.join()
            session.worker = None
        session.idle.wait()
        close = getattr(session.adapter, "close", None)
        if close:
            close()

    def status(self, key=None):
        with self._lock:
            sessions = [self._sessions[key]] if key is not None else list(self._sessions.values())
        result = []
        for session in sessions:
            with session.lock:
                data = session.data
                healthy = session.healthy and data is not None and data.expires_at > self._clock()
                result.append(
                    {
                        "id": session.key,
                        "label": session.label,
                        "state": "connected"
                        if healthy
                        else "retrying"
                        if session.connected
                        else "disconnected",
                        "message": session.message,
                        "transport": session.adapter.transport_status()
                        if hasattr(session.adapter, "transport_status")
                        else None,
                        "accounts": list(data.accounts) if data else [],
                        "expires_at": datetime.fromtimestamp(data.expires_at, UTC).isoformat()
                        if data
                        else None,
                        "refresh_at": datetime.fromtimestamp(session.next_refresh, UTC).isoformat()
                        if session.next_refresh is not None
                        else None,
                    }
                )
        return result[0] if key is not None else result

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closing = True
            keys = list(self._sessions)
        for key in keys:
            self.disconnect(key)
            self._sessions[key].executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            self._closed = True
