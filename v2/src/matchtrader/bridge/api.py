"""Facade for the local shadow bridge; its journal is owned and closed here."""

from datetime import UTC, datetime
from pathlib import Path

from .event import OrderEvent
from .journal import Journal
from .planner import preview


class ShadowBridge:
    def __init__(self, account_id: str, journal_path: str | Path, *, max_age_seconds: float = 30):
        if not account_id.strip() or max_age_seconds <= 0:
            raise ValueError("Explicit account and positive maximum event age required")
        self.account_id = account_id.strip()
        self.max_age_seconds = max_age_seconds
        self.journal = Journal(journal_path)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.journal.close()

    def receive(self, payload: dict, *, received_at: datetime | None = None):
        event = OrderEvent.model_validate(payload)
        received_at = received_at or datetime.now(UTC)
        if received_at.utcoffset() is None:
            raise ValueError("Receipt timestamp must include timezone")
        received_at = received_at.astimezone(UTC)
        return self.journal.record(
            event,
            received_at.isoformat(),
            lambda: preview(event, self.account_id, received_at, self.max_age_seconds),
        )
