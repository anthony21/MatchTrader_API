"""Observe newly appended complete R01 CSV lines; never infer executable orders."""

import csv
import io
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .journal import Journal


class LedgerTail:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.stream = self.path.open("rb")
        self.header = next(csv.reader([self.stream.readline().decode("utf-8-sig").rstrip()]))
        if not {"utc", "kind", "label", "symbol", "side", "entry", "sl", "tp"} <= set(self.header):
            self.stream.close()
            raise ValueError("Unrecognized R01 ledger header")
        self.stream.seek(0, 2)
        self.offset = self.stream.tell()
        self.skip_partial = False
        if self.offset:
            self.stream.seek(-1, 2)
            self.skip_partial = self.stream.read(1) != b"\n"
        self.stream.seek(self.offset)

    def close(self):
        self.stream.close()

    def poll(self):
        # Stop on truncation/replacement; resuming from byte zero would replay history.
        stat = self.path.stat()
        if stat.st_size < self.offset or not os.path.samestat(stat, os.fstat(self.stream.fileno())):
            raise RuntimeError("Ledger rotated or truncated; restart observation from its new EOF")
        rows = []
        for _ in range(1000):
            start = self.stream.tell()
            raw = self.stream.readline()
            if not raw or not raw.endswith(b"\n"):
                self.stream.seek(start)
                break
            self.offset = self.stream.tell()
            if self.skip_partial:
                self.skip_partial = False
                continue
            parsed = csv.DictReader(io.StringIO(raw.decode("utf-8")), fieldnames=self.header)
            record = next(parsed)
            extra = record.pop(None, [])
            rows.append(
                (
                    start,
                    {
                        "record": record,
                        "extra_fields": extra,
                        "classification": "ledger_observation_only",
                        "execution_status": "not_submitted",
                        "reason": "ledger_has_no_volume_or_verified_outbound_order_contract",
                    },
                )
            )
        return rows


def observe(path: Path, journal: Journal, *, seconds: float = 30):
    if not 0 < seconds <= 3600:
        raise ValueError("Observation duration must be between 0 and 3600 seconds")
    counts = Counter()
    started = datetime.now(UTC).isoformat()
    tail = LedgerTail(path)
    start_offset = tail.offset
    try:
        deadline = time.monotonic() + seconds
        while True:
            for offset, payload in tail.poll():
                journal.observe(datetime.now(UTC).isoformat(), str(tail.path), offset, payload)
                counts[payload["record"]["kind"] or "unknown"] += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.25, remaining))
        return {
            "mode": "shadow",
            "started_at": started,
            "ended_at": datetime.now(UTC).isoformat(),
            "start_byte": start_offset,
            "end_byte": tail.offset,
            "new_observations": sum(counts.values()),
            "kinds": dict(counts),
            "broker_orders_sent": 0,
        }
    finally:
        tail.close()
