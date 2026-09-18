import pytest
from pydantic import ValidationError

from matchtrader.capture.event import CaptureEvent


@pytest.mark.parametrize(
    "change",
    [
        {"emitted_at": "2026-09-09T00:00:00"},
        {"quantity": "NaN"},
        {"source": "Probably manual"},
        {"token": "secret"},
    ],
)
def test_untrusted_event_validation(event, change):
    with pytest.raises(ValidationError):
        CaptureEvent.model_validate({**event.model_dump(), **change})
