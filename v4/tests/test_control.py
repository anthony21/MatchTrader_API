"""The launcher's non-process parts: .env scanning and prompting, the hidden child's command, auto-start."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('control', Path(__file__).parents[1] / 'scripts' / 'control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def test_env_reader_strips_quotes_and_ignores_comments(tmp_path):
    env = tmp_path / '.env'
    env.write_text("# comment\nAQF_PLATFORM_URL='https://x.example'\nAQF_EMAIL=\"me@x\"\nAQF_ENABLE_WRITES=true\n\n", encoding='utf-8')
    values = control.read_env(env)
    assert values == {'AQF_PLATFORM_URL': 'https://x.example', 'AQF_EMAIL': 'me@x', 'AQF_ENABLE_WRITES': 'true'}
    assert control.read_env(tmp_path / 'missing') == {}


def test_setup_prompts_only_for_missing_values_never_echoes_the_password_and_keeps_the_rest(tmp_path):
    env = tmp_path / '.env'
    env.write_text("# keep me\nAQF_PLATFORM_URL='https://platform.aquafunded.com'\nAQF_ENABLE_WRITES=false\n", encoding='utf-8')
    asked, printed = [], []
    answers = iter(['me@example.com', '', '276954', '', ''])   # email, (password via secret), account, broker id, ledger

    def ask(prompt):
        asked.append(prompt)
        return next(answers)

    def ask_secret(prompt):
        asked.append('SECRET:' + prompt)
        return 'hunter22'

    values = control.ensure_env(env, ask=ask, ask_secret=ask_secret, out=printed.append)
    assert values['AQF_EMAIL'] == 'me@example.com' and values['AQF_PASSWORD'] == 'hunter22'
    assert values['AQF_ACCOUNT_ID'] == '276954' and values['AQF_R01_LEDGER'] == 'C:/HCAMM/trials/R01_TRADES.csv'
    assert len(values['AQF_BRIDGE_TOKEN']) >= 32
    assert not any(p.startswith('SECRET') is False and 'URL' in p for p in asked)   # the URL was present: not asked
    assert 'hunter22' not in ' '.join(printed)
    text = env.read_text(encoding='utf-8')
    assert text.startswith('# keep me\n') and 'AQF_ENABLE_WRITES=false' in text and 'AQF_PASSWORD=hunter22' in text
    # A second run asks nothing and changes nothing.
    again = control.ensure_env(env, ask=lambda p: pytest.fail('asked ' + p), ask_secret=lambda p: pytest.fail('asked secret'), out=printed.append)
    assert again['AQF_ACCOUNT_ID'] == '276954' and env.read_text(encoding='utf-8') == text


def test_setup_insists_on_a_value_and_uses_the_default_url(tmp_path):
    env = tmp_path / '.env'
    answers = iter(['', '', 'me@x', '', '1', '', ''])   # url twice blank -> default; email blank then given
    values = control.ensure_env(env, ask=lambda p: next(answers), ask_secret=lambda p: 'pw', out=lambda *_: None)
    assert values['AQF_PLATFORM_URL'] == 'https://platform.aquafunded.com' and values['AQF_EMAIL'] == 'me@x'


def test_hidden_child_runs_headless_with_the_same_config_and_auto_start():
    args = SimpleNamespace(config=Path('C:/x/local-runtime.json'), runtime=Path('C:/x/data/runtime'), auto_start=True)
    command = control.child_command(args)
    assert command[0] == sys.executable and command[1].endswith('control.py')
    assert '--no-console' in command and '--no-browser' in command and '--auto-start' in command
    assert command[command.index('--config') + 1] == 'C:\\x\\local-runtime.json' or command[command.index('--config') + 1] == 'C:/x/local-runtime.json'
    assert '--auto-start' not in control.child_command(SimpleNamespace(config=args.config, runtime=args.runtime, auto_start=False))


def test_auto_start_connects_the_configured_account_then_starts_capture(monkeypatch):
    calls, logged = [], []

    def fake_api(url, path, body=None, token=None, timeout=20):
        calls.append((path, body, token))
        if path == '/api/session':
            return {'token': 'tok'}
        if path == '/api/connect':
            return {'connection': 'connected', 'connection_message': 'Connected. Copying is disabled.'}
        if path == '/api/capture/start':
            return {'running': True, 'capture_message': 'Native event receiver enabled'}
        raise AssertionError(path)

    monkeypatch.setattr(control, 'api_call', fake_api)
    assert control.auto_start('http://127.0.0.1:8765', '276954', logged.append) is True
    assert [c[0] for c in calls] == ['/api/session', '/api/connect', '/api/capture/start']
    assert calls[1] == ('/api/connect', {'account_id': '276954'}, 'tok')
    assert any('connect 276954 -> connected' in line for line in logged) and any('capture -> running' in line for line in logged)

    # A failed connect still starts capture and reports both.
    def flaky(url, path, body=None, token=None, timeout=20):
        if path == '/api/connect':
            raise OSError('broker down')
        return fake_api(url, path, body, token, timeout)
    monkeypatch.setattr(control, 'api_call', flaky)
    logged.clear()
    assert control.auto_start('http://127.0.0.1:8765', '276954', logged.append) is False
    assert any('connect failed' in line for line in logged) and any('capture -> running' in line for line in logged)


def test_stop_flag_only_touches_the_stop_file(tmp_path):
    config = tmp_path / 'local-runtime.json'
    config.write_text(json.dumps({'dashboard_port': 8765}))
    assert control.main(['--stop', '--runtime', str(tmp_path / 'rt'), '--config', str(config)]) == 0
    assert (tmp_path / 'rt' / 'stop.requested').exists()
