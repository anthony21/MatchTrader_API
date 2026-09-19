import pytest

from matchtrader.sessions.profiles import load_profiles


def test_legacy_and_multiple_broker_configuration():
    env = {"MTR_PLATFORM_URL": "https://aqua.example", "MTR_ACCOUNT_ID": "123"}
    assert load_profiles(env)[0].key == "DEFAULT"
    env.update(
        MTR_BROKERS="AQUA,GTR",
        MTR_PRIMARY_BROKER="AQUA",
        GTR_PLATFORM_URL="https://gooey.example",
        GTR_ACCOUNT_ID="456",
        GTR_LABEL="GooeyTrade",
    )
    profiles = load_profiles(env)
    assert [(p.key, p.settings.account_id) for p in profiles] == [("AQUA", "123"), ("GTR", "456")]
    assert profiles[1].label == "GooeyTrade"
    env.update(
        MTR_HTTP_EXPECTED_CONCURRENCY="32", MTR_HTTP_MAX_CONNECTIONS="40", GTR_HTTP_CONNECT_TIMEOUT="1.0"
    )
    profiles = load_profiles(env)
    assert profiles[0].transport.max_connections == 40
    assert profiles[0].transport.expected_concurrency == 32
    assert profiles[1].transport.connect_timeout == 1.0


@pytest.mark.parametrize("keys", ["AQUA,AQUA", "../AQUA", "", "aqua", "A,B/../C"])
def test_invalid_profile_keys(keys):
    with pytest.raises(ValueError):
        load_profiles({"MTR_BROKERS": keys})
