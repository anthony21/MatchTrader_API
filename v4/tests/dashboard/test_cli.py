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
    main(['--assets', str(tmp_path), '--env', str(environment), '--ws-port', str(ws_port)])
    assert calls == (['ws-start', 'ws-close', 'controller-close'] if ws_port else ['controller-close'])
