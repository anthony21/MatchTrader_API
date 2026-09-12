"""User-operated MatchTrader API lifecycle: dashboard, relay and collector. No scheduled tasks or automatic startup."""
import argparse
import json
import os
import socket
import subprocess
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--config', type=Path, default=ROOT / 'local-runtime.json')
    parser.add_argument('--runtime', type=Path, default=ROOT / 'data' / 'runtime')
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    stop = runtime / 'stop.requested'
    if args.stop:
        stop.touch()
        print('Stop requested. The launcher will finish active exchanges and close all three services.')
        return
    import msvcrt
    lock = (runtime / 'launcher.lock').open('a+b')
    lock.seek(0)
    lock.write(b'0')
    lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise SystemExit('The MatchTrader API is already running. Use its window or Stop MatchTrader.') from None
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    # Relative entries resolve against the config file, so a checked-in example works from any shell.
    python, env_file, data, relay_config, logs, checkpoint = [
        str((args.config.resolve().parent / config[key]).resolve())
        for key in ['python', 'env', 'data', 'relay_config', 'logs', 'checkpoint']]
    if not Path(python).is_file() or not Path(env_file).is_file():
        raise SystemExit('The local Python environment or credentials file is missing. Check local-runtime.json.')
    Path(logs).mkdir(parents=True, exist_ok=True)  # The collector refuses a missing log directory.
    dashboard_port, ws_port, relay_port = [int(config.get(key, default)) for key, default in [('dashboard_port', 8765), ('ws_port', 8767), ('relay_port', 8787)]]
    url = f'http://127.0.0.1:{dashboard_port}'
    for port in (dashboard_port, ws_port, relay_port):
        if port == 0:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                raise SystemExit(f'Port {port} is already in use. Stop the existing application first.') from None
    (runtime / 'launcher.pid').write_text(str(os.getpid()))
    stop.unlink(missing_ok=True)
    signals = {name: runtime / f'{name}.stop' for name in ['dashboard', 'relay', 'collector']}
    for flag in signals.values():
        flag.unlink(missing_ok=True)
    environment = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONUNBUFFERED='1', HCAMM_CONTROL_LOCK=str(runtime / 'launcher.lock'))
    commands = {
        'dashboard': ['-m', 'matchtrader.dashboard.cli', '--env', env_file, '--data', data, '--assets', str(ROOT / 'frontend' / 'dist'), '--port', str(dashboard_port), '--ws-port', str(ws_port)],
        'relay': [str(ROOT / 'relay' / 'tb-relay.py'), '--config', relay_config, '--port', str(relay_port), '--env', env_file, '--receiver-port', str(dashboard_port)],
        'collector': ['-m', 'matchtrader.capture.relay_collector', '--env', env_file, '--logs', logs, '--state', checkpoint, '--endpoint', url + '/relay/logs'],
    }
    children, handles = {}, []
    try:
        for name, command in commands.items():
            stream = (runtime / f'{name}.log').open('ab')
            handles.append(stream)
            children[name] = subprocess.Popen([python, '-u', *command, '--stop-file', str(signals[name])], cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        ready = False
        for _ in range(80):
            if stop.exists() or any(child.poll() is not None for child in children.values()):
                break
            try:
                with opener.open(url + '/api/session', timeout=1):
                    ready = True
                break
            except OSError:
                time.sleep(0.25)
        if not ready:
            raise RuntimeError('Startup did not finish. See data/runtime logs.')
        print(f'MatchTrader API is ON: {url}\nPress Enter here, use Stop MatchTrader, or click Shut down API to turn it off.', flush=True)
        if not args.no_browser:
            webbrowser.open(url + '/?page=raw')
        while not stop.exists() and all(child.poll() is None for child in children.values()):
            if msvcrt.kbhit() and msvcrt.getwch() in {'\r', '\n'}:
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        print('Stopping the MatchTrader API; finishing active requests and retaining logs...', flush=True)
        # Stop ingress first. Let the collector catch up before the receiver exits.
        for name in ['relay', 'collector', 'dashboard']:
            signals[name].touch()
            child = children.get(name)
            if child:
                try:
                    child.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True, check=False)
        for handle in handles:
            handle.close()
        lock.close()
        print('MatchTrader API is OFF. It will stay off until you start it.', flush=True)


if __name__ == '__main__':
    main()
