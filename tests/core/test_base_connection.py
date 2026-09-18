import pytest

from matchtrader.core.errors import ConfigurationError
from matchtrader.core.rest_connection import RestConnection


def test_constructor_requires_factory(settings):
    with pytest.raises(ConfigurationError):
        RestConnection(settings)


def test_shared_leases_and_same_account_config_conflict(api_factory, settings):
    api, _ = api_factory()
    other = RestConnection.acquire(settings)
    assert api.connection is other
    with pytest.raises(ConfigurationError):
        RestConnection.acquire(settings.model_copy(update={"timeout_seconds": 30}))
    api.close()
    assert not other.closed
    other.release()
    assert other.closed
    fresh = RestConnection.acquire(settings)
    assert fresh is not other
    fresh.release()
