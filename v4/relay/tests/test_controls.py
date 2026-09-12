"""Exercise user start/stop and orphan cleanup on isolated loopback ports."""
import base64
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def available_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def wait_for(check, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if check():
                return
        except OSError:
            pass
        time.sleep(0.15)
    raise AssertionError('Lifecycle condition timed out')


def listening(port):
    with socket.socket() as client:
        client.settimeout(0.1)
        return client.connect_ex(('127.0.0.1', port)) == 0


@pytest.mark.skipif(os.name != 'nt', reason='Windows launcher')
@pytest.mark.parametrize('stop_mode', ['button', 'stop-file', 'window-closed'])
def test_user_controls_all_services_and_closing_launcher_leaves_no_listeners(tmp_path, stop_mode):
    dashboard_port, relay_port = available_port(), available_port()
    environment = tmp_path / 'test.env'
    environment.write_text('MTR_PLATFORM_URL=https://broker.example\nMTR_ACCOUNT_ID=test\nMTR_BRIDGE_TOKEN=local-test-token-with-at-least-32-characters\n')
    logs = tmp_path / 'logs'
    logs.mkdir()
    relay = tmp_path / 'relay.json'
    # No request is sent upstream by this test. The unreachable origin is deliberate.
    relay.write_text(json.dumps({'upstream': 'http://127.0.0.1:1', 'logDir': str(logs), 'forward': False}))
    config = tmp_path / 'runtime.json'
    config.write_text(json.dumps({'python': sys.executable, 'env': str(environment), 'data': str(tmp_path / 'archive'),
                                 'relay_config': str(relay), 'logs': str(logs), 'checkpoint': str(tmp_path / 'collector.sqlite3'),
                                 'dashboard_port': dashboard_port, 'relay_port': relay_port, 'ws_port': 0}))
    runtime = tmp_path / 'run'
    output = (tmp_path / 'launcher.log').open('wb')
    child = subprocess.Popen([sys.executable, str(ROOT / 'scripts/control.py'), '--no-browser', '--config', str(config), '--runtime', str(runtime)],
                             stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        wait_for(lambda: listening(dashboard_port) and listening(relay_port))
        client = http.client.HTTPConnection('127.0.0.1', relay_port, timeout=5)
        client.request('POST', '/api/hcamm/events', body=b'[{"unknown":"lifecycle-proof"}]')
        reply = client.getresponse()
        assert reply.status == 202
        reply.read()
        client.close()
        def archived():
            client = http.client.HTTPConnection('127.0.0.1', dashboard_port, timeout=5)
            client.request('GET', '/api/session')
            token = json.loads(client.getresponse().read())['token']
            client.close()
            client = http.client.HTTPConnection('127.0.0.1', dashboard_port, timeout=5)
            client.request('GET', '/api/relay/logs', headers={'X-Session-Token': token})
            page = json.loads(client.getresponse().read())
            client.close()
            # The collector ships the relay's own jsonl archive; prove both halves of the cycle arrived.
            records = {'request': [], 'response': []}
            for chunk in page['records']:
                direction = 'request' if chunk['filename'].startswith('raw-request') else 'response'
                for line in base64.b64decode(chunk['data_base64']).decode('utf-8', errors='replace').splitlines():
                    if line.strip():
                        records[direction].append(json.loads(line))
            return (any(b'lifecycle-proof' in base64.b64decode(r['body_base64']) for r in records['request'])
                    and any(r.get('origin') == 'x.0.1' for r in records['response']))
        wait_for(archived)
        if stop_mode == 'window-closed':
            # Terminate just the actual interpreter, not its descendants: their lock watcher must close them.
            import ctypes
            from ctypes import wintypes
            # The redirector is the Popen PID; ask the launcher for its actual interpreter PID via its file.
            pid = int((runtime / 'launcher.pid').read_text())
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(1, False, pid)
            assert handle
            assert kernel.TerminateProcess(handle, 0)
            kernel.CloseHandle(handle)
        elif stop_mode == 'stop-file':
            subprocess.run([sys.executable, str(ROOT / 'scripts/control.py'), '--stop', '--runtime', str(runtime)], check=True, capture_output=True)
        else:
            client = http.client.HTTPConnection('127.0.0.1', dashboard_port, timeout=5)
            client.request('GET', '/api/session')
            token = json.loads(client.getresponse().read())['token']
            client.close()
            client = http.client.HTTPConnection('127.0.0.1', dashboard_port, timeout=5)
            client.request('POST', '/api/shutdown', body=b'{}', headers={'X-Session-Token': token, 'Content-Type': 'application/json'})
            assert client.getresponse().status == 200
            client.close()
        wait_for(lambda: not listening(dashboard_port) and not listening(relay_port))
        child.wait(timeout=15)
    finally:
        (runtime / 'stop.requested').touch()
        if child.poll() is None:
            child.wait(timeout=50)
        output.close()
