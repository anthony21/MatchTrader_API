from matchtrader.capture import CaptureEvent, CaptureStore


def test_capture_public_contract():
    assert CaptureEvent.model_fields["schema_version"].default == 1
    assert callable(CaptureStore.record)
