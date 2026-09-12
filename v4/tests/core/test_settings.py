import pytest
from pydantic import ValidationError

from matchtrader.core.settings import Settings


def test_env_precedence_and_hidden_secrets(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("AQF_PLATFORM_URL=https://broker.example\nAQF_PASSWORD=do-not-print\nAQF_ACCOUNT_ID=1")
    monkeypatch.setenv("AQF_ACCOUNT_ID", "2")
    s = Settings.from_env(env)
    assert s.account_id == "2"
    assert s.password.get_secret_value() == "do-not-print"
    assert "do-not-print" not in repr(s)


@pytest.mark.parametrize(
    "url",
    [
        "http://broker.example",
        "https://user:pass@broker.example",
        "https://broker.example/path",
        "https://broker.example?token=x",
    ],
)
def test_bad_origin_rejected(url):
    with pytest.raises(ValidationError):
        Settings(platform_url=url)


def test_bad_ws_headers_and_limits():
    with pytest.raises(ValidationError):
        Settings(platform_url="https://broker.example", ws_headers_json="[]")
    with pytest.raises(ValidationError):
        Settings(platform_url="https://broker.example", requests_per_minute=501)
    with pytest.raises(ValidationError):
        Settings(platform_url="https://broker.example", system_uuid="../../other")


def test_tls_minimum_from_env_and_invalid_versions(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AQF_PLATFORM_URL=https://broker.example\nAQF_TLS_MINIMUM_VERSION=TLSv1.3\n")
    assert Settings.from_env(env).tls_minimum_version == "TLSv1.3"
    assert Settings(platform_url="https://broker.example").tls_minimum_version == "TLSv1.3"
    for value in ("TLSv1.1", "false", "auto"):
        with pytest.raises(ValidationError):
            Settings(platform_url="https://broker.example", tls_minimum_version=value)
