"""The checked-in sender contract must match runtime validation."""

import json
from pathlib import Path

from matchtrader.capture.event import CaptureEvent


def test_published_schema_matches_receiver():
    root = Path(__file__).parents[2]
    published = json.loads((root / 'docs/schemas/capture-event-1.1.0.json').read_text())
    assert published == CaptureEvent.model_json_schema()
