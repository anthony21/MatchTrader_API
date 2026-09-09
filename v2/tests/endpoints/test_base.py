import httpx
import pytest

from matchtrader.core.errors import ProtocolError


def test_missing_collection_not_misread_as_empty(api_factory):
    api, _ = api_factory(
        lambda r: httpx.Response(200, json={}) if r.url.path.endswith("/active-orders") else None
    )
    with pytest.raises(ProtocolError):
        api.active_orders()


def test_unexpected_request_fields_rejected(api_factory):
    api, seen = api_factory()
    with pytest.raises(TypeError):
        api.balance(unexpected="x")
    assert not seen
