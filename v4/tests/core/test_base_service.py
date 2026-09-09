import pytest

from matchtrader.core.base_service import BaseService
from matchtrader.core.errors import ConnectionClosedError


def test_service_borrows_and_does_not_keep_owner_alive(api_factory):
    api, _ = api_factory()
    service = BaseService(api)
    assert service.connection is api.connection
    api.close()
    with pytest.raises(ConnectionClosedError):
        _ = service.connection
