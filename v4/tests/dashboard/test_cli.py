from types import SimpleNamespace

import pytest

from matchtrader.dashboard.cli import main


def test_dashboard_requires_built_frontend(tmp_path):
    with pytest.raises(SystemExit):
        main(["--assets", str(tmp_path)])


@pytest.mark.parametrize('ws_port', [0, 8767])
def test_websocket_lifecycle_is_owned_by_dashboard(tmp_path, monkeypatch, ws_port):
    from matchtrader.dashboard import cli

    (tmp_path / 'index.html').write_text('<html></html>')
    environment = tmp_path / '.env'
    environment.write_text('MTR_PLATFORM_URL=https://broker.example\nMTR_ACCOUNT_ID=test\n')
    monkeypatch.setenv('MTR_BRIDGE_TOKEN', 'test-token-at-least-32-characters-long')
    calls = []
    class Controller:
        def __init__(self, *args, **kwargs):
            self.capture_websocket = None
            self.logging_events = None
            self.native_store = SimpleNamespace(raw_log=None)
        def close(self):
            if self.capture_websocket:
                self.capture_websocket.close()
            calls.append('controller-close')
    class WebSocket:
        def __init__(self, controller, token, port):
            assert port == 8767
        def start(self):
            calls.append('ws-start')
        def close(self):
            calls.append('ws-close')
    class HTTP:
        server_port = 8765
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def serve_forever(self, **kwargs): raise KeyboardInterrupt
    monkeypatch.setattr(cli, 'DashboardController', Controller)
    monkeypatch.setattr(cli, 'DashboardHTTPServer', HTTP)
    monkeypatch.setattr(cli, 'CaptureWebSocketServer', WebSocket)
    main(['--assets', str(tmp_path), '--env', str(environment), '--ws-port', str(ws_port), '--data', str(tmp_path / 'data')])
    assert calls == (['ws-start', 'ws-close', 'controller-close'] if ws_port else ['controller-close'])


def test_stop_file_shuts_the_dashboard_down_and_p01_path_comes_from_env(tmp_path, monkeypatch):
    from threading import Event

    from matchtrader.dashboard import cli

    (tmp_path / 'index.html').write_text('<html></html>')
    environment = tmp_path / '.env'
    environment.write_text('MTR_PLATFORM_URL=https://broker.example\nMTR_ACCOUNT_ID=test\n'
                           'MTR_P01_LOG_PATH=C:/logs/P01_RR.log\n')
    monkeypatch.delenv('HCAMM_CONTROL_LOCK', raising=False)
    monkeypatch.delenv('MTR_BRIDGE_TOKEN', raising=False)
    monkeypatch.delenv('MTR_P01_LOG_PATH', raising=False)
    stop = tmp_path / 'dashboard.stop'
    stop.touch()
    seen = {}

    class Controller:
        def __init__(self, *args, **kwargs):
            seen['p01_log_path'] = kwargs.get('p01_log_path')
            self.capture_websocket = None
            self.logging_events = None
            self.native_store = SimpleNamespace(raw_log=None)

        def close(self):
            seen['closed'] = True

    class HTTP:
        server_port = 8765

        def __init__(self, *args, **kwargs):
            self.stopped = Event()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def shutdown(self):
            self.stopped.set()

        def serve_forever(self, **kwargs):
            assert self.stopped.wait(5), 'The stop file was not honoured'

    monkeypatch.setattr(cli, 'DashboardController', Controller)
    monkeypatch.setattr(cli, 'DashboardHTTPServer', HTTP)
    main(['--assets', str(tmp_path), '--env', str(environment), '--ws-port', '0',
          '--data', str(tmp_path / 'data'), '--stop-file', str(stop)])
    assert seen == {'p01_log_path': 'C:/logs/P01_RR.log', 'closed': True}
