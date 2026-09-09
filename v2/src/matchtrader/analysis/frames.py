"""Explicit flattening and numeric conversion; raw DTOs retain decimal precision."""

from decimal import Decimal

import pandas as pd

from matchtrader.models.base import Record


def to_frame(records, *, numeric=(), timestamps=(), naive_timezone=None):
    """Normalize records without combining parent/child positions or silently deduplicating.

    Broker time strings without offsets require an explicit naive_timezone.
    Epoch-millisecond fields should be converted explicitly by the caller with unit='ms'.
    """
    if isinstance(records, (Record, dict)):
        records = [records]
    data = [r.model_dump(by_alias=True) if isinstance(r, Record) else dict(r) for r in records]
    frame = pd.json_normalize(data)
    for column in numeric:
        if column in frame:
            frame[column] = pd.to_numeric(
                frame[column].map(lambda x: float(x) if isinstance(x, Decimal) else x), errors="raise"
            )
    for column in timestamps:
        if column not in frame:
            continue

        def parse(value):
            if value is None or pd.isna(value):
                return pd.NaT
            stamp = pd.Timestamp(value)
            if stamp.tzinfo is None:
                if naive_timezone is None:
                    raise ValueError("Timezone-less broker timestamps require naive_timezone")
                stamp = stamp.tz_localize(naive_timezone, ambiguous="raise", nonexistent="raise")
            return stamp.tz_convert("UTC")

        frame[column] = pd.to_datetime(frame[column].map(parse), utc=True)
    return frame
