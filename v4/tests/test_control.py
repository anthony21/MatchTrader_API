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


def test_an_absent_optional_key_is_asked_once_even_when_credentials_are_complete(tmp_path):
    env = tmp_path / '.env'
    env.write_text("AQF_PLATFORM_URL=https://x\nAQF_EMAIL=a\nAQF_PASSWORD=b\nAQF_ACCOUNT_ID=1\nAQF_BROKER_ID=2\n", encoding='utf-8')
    asked = []
    values = control.ensure_env(env, ask=lambda p: asked.append(p) or '', ask_secret=lambda p: pytest.fail('secret'), out=lambda *_: None)
    assert [p for p in asked if 'ledger' in p.lower()] and not [p for p in asked if 'Broker ID' in p]
    assert values['AQF_R01_LEDGER'] == 'C:/HCAMM/trials/R01_TRADES.csv'
    env.write_text("AQF_PLATFORM_URL=https://x\nAQF_EMAIL=a\nAQF_PASSWORD=b\nAQF_ACCOUNT_ID=1\nAQF_BROKER_ID=2\nAQF_R01_LEDGER=\n", encoding='utf-8')
    control.ensure_env(env, ask=lambda p: pytest.fail('asked ' + p), ask_secret=lambda p: pytest.fail('secret'), out=lambda *_: None)


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


def host(tmp_path, *, python=True, dist=True, env=None, ledger=False):
    base = tmp_path / 'v4'
    (base / '.venv' / 'Scripts').mkdir(parents=True)
    if python:
        (base / '.venv' / 'Scripts' / 'python.exe').write_text('')
    if dist:
        (base / 'frontend' / 'dist').mkdir(parents=True)
        (base / 'frontend' / 'dist' / 'index.html').write_text('<html>')
    (base / 'relay').mkdir()
    (base / 'relay' / 'relay.json').write_text('{}')
    if env is not None:
        (base / '.env').write_text(env)
    if ledger:
        (tmp_path / 'R01_TRADES.csv').write_text('utc,kind\n')
    config = base / 'local-runtime.json'
    config.write_text(json.dumps({'python': '.venv/Scripts/python.exe', 'env': '.env', 'data': 'data',
                                  'relay_config': 'relay/relay.json', 'logs': 'data/relay_logs/logs',
                                  'checkpoint': 'data/relay_logs/delivery/collector.sqlite3',
                                  'dashboard_port': 0, 'ws_port': 0, 'relay_port': 0}))
    return config


check_host = control.check_host


def statuses(rows):
    return {name: status for status, name, _ in rows}


def test_host_check_passes_a_complete_machine_and_reports_the_optional_pieces(tmp_path):
    ledger = tmp_path / 'R01_TRADES.csv'
    env = (f"AQF_PLATFORM_URL=https://x.example\nAQF_EMAIL=me@x\nAQF_PASSWORD=pw\nAQF_ACCOUNT_ID=1\n"
           f"AQF_ENABLE_WRITES=true\nAQF_R01_LEDGER={ledger.as_posix()}\nAQF_P01_LOG_PATH={(tmp_path / 'nope.log').as_posix()}\n")
    config = host(tmp_path, env=env, ledger=True)
    rows = check_host(config, probe=lambda url: 200)
    s = statuses(rows)
    assert s['Python 3.12 or later'] == 'OK' and s['Windows'] == 'OK'
    assert s['Python environment (.venv)'] == 'OK' and s['Dashboard build (frontend/dist)'] == 'OK'
    assert s['Credentials (.env)'] == 'OK' and s['Broker writes'] == 'OK' and s['R01 ledger'] == 'OK'
    assert s['P01 log'] == 'WARN' and s['Broker reachable over TLS 1.3'] == 'OK' and s['Data folder writable'] == 'OK'
    assert 'FAIL' not in s.values()
    printed = []
    assert control.print_check(rows, out=printed.append) is True
    assert printed[-1].endswith('failures') and '0 failures' in printed[-1]


def test_host_check_fails_on_missing_pieces_and_warns_before_setup(tmp_path):
    config = host(tmp_path, python=False, dist=False, env="AQF_PLATFORM_URL=https://x.example\n")
    rows = check_host(config, probe=lambda url: (_ for _ in ()).throw(OSError('offline')))
    s = statuses(rows)
    assert s['Python environment (.venv)'] == 'FAIL' and s['Dashboard build (frontend/dist)'] == 'FAIL'
    assert s['Credentials (.env)'] == 'WARN' and s['Broker writes'] == 'WARN' and s['R01 ledger'] == 'WARN'
    assert s['Broker reachable over TLS 1.3'] == 'WARN'
    assert control.print_check(rows, out=lambda *_: None) is False
    assert control.main(['--check', '--config', str(config), '--runtime', str(tmp_path / 'rt')]) == 1


def test_host_check_flags_a_port_already_in_use(tmp_path):
    import socket
    config = host(tmp_path, env="AQF_PLATFORM_URL=https://x.example\n")
    holder = socket.socket()
    holder.bind(('127.0.0.1', 0))
    port = holder.getsockname()[1]
    cfg = json.loads(config.read_text())
    cfg['dashboard_port'] = port
    config.write_text(json.dumps(cfg))
    try:
        s = statuses(check_host(config, probe=lambda url: 200))
        assert s[f'Port {port} (dashboard_port)'] == 'FAIL'
    finally:
        holder.close()
    assert statuses(check_host(config, probe=lambda url: 200))[f'Port {port} (dashboard_port)'] == 'OK'


def test_a_bare_check_reports_and_never_starts_the_launcher(tmp_path, monkeypatch):
    config = host(tmp_path, env="AQF_PLATFORM_URL=https://x.example\nAQF_EMAIL=a\nAQF_PASSWORD=b\nAQF_ACCOUNT_ID=1\n")
    monkeypatch.setattr(control, 'check_host', lambda path, **kw: [('OK', 'Python 3.12 or later', '')])
    monkeypatch.setattr(control, 'run', lambda args: pytest.fail('a bare --check must not start the launcher'))
    monkeypatch.setattr(control, 'detach', lambda args, url: pytest.fail('a bare --check must not detach'))
    assert control.main(['--check', '--config', str(config), '--runtime', str(tmp_path / 'rt')]) == 0


def test_missing_runtime_config_is_the_first_and_only_failure(tmp_path):
    rows = control.check_host(tmp_path / 'nowhere.json')
    assert rows[-1][0] == 'FAIL' and 'local-runtime.json' in rows[-1][1]


def test_stop_flag_only_touches_the_stop_file(tmp_path):
    config = tmp_path / 'local-runtime.json'
    config.write_text(json.dumps({'dashboard_port': 8765}))
    assert control.main(['--stop', '--runtime', str(tmp_path / 'rt'), '--config', str(config)]) == 0
    assert (tmp_path / 'rt' / 'stop.requested').exists()
