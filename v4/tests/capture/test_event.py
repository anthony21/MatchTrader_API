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
        {"schema_version": "2.0.0"},
        {"remaining_quantity": "-1"},
        {"fill_effect": "probably-open"},
    ],
)
def test_untrusted_event_validation(event, change):
    with pytest.raises(ValidationError):
        CaptureEvent.model_validate({**event.model_dump(), **change})


@pytest.mark.parametrize('version', [1, '1.0.0', '1.1.0'])
def test_legacy_and_semantic_contracts_preserve_partial_quantities(event, version):
    parsed = CaptureEvent.model_validate({**event.model_dump(), 'schema_version': version,
                                         'emitted_at': '2026-09-09T12:00:00-07:00',
                                         'order_quantity': '1', 'cumulative_filled_quantity': '.4',
                                         'remaining_quantity': '.6', 'quantity_unit': 'contracts'})
    assert parsed.emitted_at.isoformat() == '2026-09-09T19:00:00+00:00'
    assert str(parsed.remaining_quantity) == '0.6'
