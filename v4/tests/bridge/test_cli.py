import json

import pytest

from matchtrader.bridge.cli import main


def test_observe_cli_loads_only_local_account(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("AQF_ACCOUNT_ID=123\nAQF_PASSWORD=secret-not-for-output\n")
    monkeypatch.delenv("AQF_ACCOUNT_ID", raising=False)
    monkeypatch.setattr("matchtrader.bridge.cli.observe", lambda *a, **k: {"broker_orders_sent": 0})
    main(["--env", str(env), "--journal", str(tmp_path / "journal.db"), "observe", "--ledger", "unused.csv"])
    output = capsys.readouterr().out
    assert json.loads(output)["intended_account_id"] == "123"
    assert "secret-not-for-output" not in output


def test_cli_requires_explicit_account(tmp_path, monkeypatch):
    monkeypatch.delenv("AQF_ACCOUNT_ID", raising=False)
    with pytest.raises(SystemExit):
        main(["--env", str(tmp_path / "missing.env"), "serve"])
