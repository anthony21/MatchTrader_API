import pytest

from matchtrader.cli import main


def test_help_needs_no_credentials(capsys):
    with pytest.raises(SystemExit) as exit:
        main(["--help"])
    assert exit.value.code == 0
    assert "snapshot" in capsys.readouterr().out


def test_invalid_environment_does_not_echo_secret(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("AQF_PLATFORM_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("AQF_PLATFORM_URL=http://secret@example.com\nAQF_PASSWORD=hidden-password")
    assert main(["--env", str(env), "balance"]) == 2
    assert "hidden-password" not in capsys.readouterr().out


def test_snapshot_exports_all_read_categories(tmp_path, monkeypatch, api_factory, settings):
    import json
    from pathlib import Path

    import httpx

    import matchtrader.cli as cli

    cases = json.loads((Path(__file__).parent / "fixtures/endpoints.json").read_text())

    def handler(r):
        for case in cases.values():
            if r.url.path == case["path"].replace("SYSTEM_UUID", "system-1") and case["body"] is not None:
                return httpx.Response(200, json=case["body"])

    api, _ = api_factory(handler)
    monkeypatch.setattr(cli.Settings, "from_env", lambda _: settings)
    monkeypatch.setattr(cli, "MatchTraderAPI", lambda _: api)
    args = [
        "snapshot",
        "--symbols",
        "EURUSD",
        "--from",
        "2026-09-07T00:00:00Z",
        "--to",
        "2026-09-08T00:00:00Z",
        "--output",
        str(tmp_path),
    ]
    assert cli.main(args) == 0
    assert len(list(tmp_path.glob("*.csv"))) == 7
    assert len(list(tmp_path.glob("*.json"))) == 8
    assert json.loads((tmp_path / "manifest.json").read_text())["account_id"] == "123"
    assert "session-test" not in "".join(p.read_text() for p in tmp_path.glob("*.json"))
    assert api.closed


def test_cli_api_error_is_reported_without_traceback(monkeypatch, api_factory, settings, capsys):
    import httpx

    import matchtrader.cli as cli

    api, _ = api_factory(lambda _: httpx.Response(503, text="private"))
    monkeypatch.setattr(cli.Settings, "from_env", lambda _: settings)
    monkeypatch.setattr(cli, "MatchTraderAPI", lambda _: api)
    assert cli.main(["platform"]) == 2
    assert "private" not in capsys.readouterr().out
