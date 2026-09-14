"""User-operated MatchTrader API lifecycle: dashboard, relay and collector.

    Start MatchTrader.cmd  ->  control.py --setup --detach
        1. --setup    reads .env, asks for anything missing (password never echoed), writes it back
        2. --detach   starts the launcher as a hidden child, waits until the dashboard answers,
                      opens the browser, and returns so the console window can close
    The hidden child (--no-console --auto-start) runs the three services, connects the configured
    account, starts capture, and keeps them alive until Stop MatchTrader.cmd writes the stop file.

No scheduled tasks or automatic startup after reboot.
"""
import argparse
import getpass
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# What the launcher needs before it can start and connect. (key, prompt, default, secret)
REQUIRED = [
    ('AQF_PLATFORM_URL', 'Match-Trader terminal URL', 'https://platform.aquafunded.com', False),
    ('AQF_EMAIL', 'Broker login email', '', False),
    ('AQF_PASSWORD', 'Broker login password', '', True),
    ('AQF_ACCOUNT_ID', 'Trading account ID to connect', '', False),
]
OPTIONAL = [
    ('AQF_BROKER_ID', 'Broker ID (blank to discover it at login)', '', False),
    ('AQF_R01_LEDGER', 'R01 ledger CSV path (blank to skip R01 observation)', 'C:/HCAMM/trials/R01_TRADES.csv', False),
]


# ---- .env --------------------------------------------------------------------------------------
def read_env(path):
    """Key -> value for the simple KEY=value lines in .env; quotes stripped, comments kept out."""
    values = {}
    if not Path(path).exists():
        return values
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, _, value = stripped.partition('=')
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
            value = value[1:-1]
        values[key.strip()] = value
    return values


def write_env(path, updates):
    """Set or append KEY=value lines, keeping every other line and comment exactly as it was."""
    path = Path(path)
    lines = path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
    pending = dict(updates)
    out = []
    for line in lines:
        key = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else None
        if key in pending:
            out.append(f'{key}={pending.pop(key)}')
        else:
            out.append(line)
    out.extend(f'{key}={value}' for key, value in pending.items())
    path.write_text('\n'.join(out) + '\n', encoding='utf-8')


def ensure_env(path, *, ask=input, ask_secret=getpass.getpass, out=print):
    """Ask only for what is missing; never echo a secret; generate the local bridge token."""
    values = read_env(path)
    updates = {}
    missing = [item for item in REQUIRED if not values.get(item[0])]
    if missing:
        out(f'Credentials needed in {path}:')
    for key, prompt, default, secret in missing:
        while True:
            suffix = f' [{default}]' if default else ''
            answer = (ask_secret(f'  {prompt}: ') if secret else ask(f'  {prompt}{suffix}: ')).strip()
            if not answer and default:
                answer = default
            if answer:
                break
            out('    A value is required.')
        updates[key] = answer
    if missing:
        for key, prompt, default, _secret in OPTIONAL:
            if values.get(key):
                continue
            suffix = f' [{default}]' if default else ''
            answer = ask(f'  {prompt}{suffix}: ').strip() or default
            if answer:
                updates[key] = answer
    if not values.get('AQF_BRIDGE_TOKEN'):
        updates['AQF_BRIDGE_TOKEN'] = secrets.token_urlsafe(32)
        out('  Generated a local bridge token (AQF_BRIDGE_TOKEN) for the Quantower extension.')
    if updates:
        write_env(path, updates)
        out(f'  Saved {", ".join(updates)} to {path}.')
    values.update(updates)
    return values


# ---- dashboard API -------------------------------------------------------------------------------
def api_call(url, path, body=None, token=None, timeout=20):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['X-Session-Token'] = token
    request = urllib.request.Request(url + path, data=data, headers=headers, method='POST' if body is not None else 'GET')
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read() or b'{}')


def wait_ready(url, *, attempts=80, pause=0.25, stop=None):
    for _ in range(attempts):
        if stop is not None and stop():
            return False
        try:
            api_call(url, '/api/session', timeout=1)
            return True
        except OSError:
            time.sleep(pause)
    return False


def auto_start(url, account_id, log):
    """Connect the configured account and start capture, through the dashboard's own API."""
    try:
        token = api_call(url, '/api/session')['token']
    except (OSError, KeyError, ValueError) as error:
        log(f'auto-start: no session token ({type(error).__name__}); connect and start capture by hand')
        return False
    ok = True
    if account_id:
        try:
            status = api_call(url, '/api/connect', {'account_id': account_id}, token, timeout=60)
            log(f"auto-start: connect {account_id} -> {status.get('connection')} {status.get('connection_message', '')}")
            ok = status.get('connection') == 'connected'
        except OSError as error:
            log(f'auto-start: connect failed ({type(error).__name__}); capture will still start')
            ok = False
    try:
        status = api_call(url, '/api/capture/start', {}, token, timeout=30)
        log(f"auto-start: capture -> {'running' if status.get('running') else 'stopped'}; {status.get('capture_message', '')}")
    except OSError as error:
        log(f'auto-start: capture start failed ({type(error).__name__})')
        ok = False
    return ok


# ---- launcher -----------------------------------------------------------------------------------
def child_command(args):
    """The hidden launcher's command line: same interpreter, same config, no console, auto-start."""
    command = [sys.executable, str(Path(__file__).resolve()), '--no-console', '--no-browser',
               '--config', str(args.config), '--runtime', str(args.runtime)]
    if args.auto_start:
        command.append('--auto-start')
    return command


def detach(args, url):
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    log_path = runtime / 'launcher.log'
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) \
        | getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    with log_path.open('ab') as stream:
        child = subprocess.Popen(child_command(args), cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream,
                                 stderr=subprocess.STDOUT, creationflags=flags, close_fds=True)
    print(f'Starting the MatchTrader API in the background (pid {child.pid})...', flush=True)
    if not wait_ready(url, attempts=240, stop=lambda: child.poll() is not None):
        print(f'The API did not come up. See {log_path}', flush=True)
        return 1
    print(f'MatchTrader API is ON: {url}\nUse Stop MatchTrader to turn it off. Log: {log_path}', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    return 0


def run(args):
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    stop = runtime / 'stop.requested'

    def log(message):
        print(f'{time.strftime("%Y-%m-%dT%H:%M:%S")} {message}', flush=True)

    import msvcrt
    lock = (runtime / 'launcher.lock').open('a+b')
    lock.seek(0)
    lock.write(b'0')
    lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise SystemExit('The MatchTrader API is already running. Use Stop MatchTrader first.') from None
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
        ready = wait_ready(url, stop=lambda: stop.exists() or any(child.poll() is not None for child in children.values()))
        if not ready:
            raise RuntimeError('Startup did not finish. See data/runtime logs.')
        log(f'MatchTrader API is ON: {url}')
        if args.auto_start:
            auto_start(url, read_env(env_file).get('AQF_ACCOUNT_ID', ''), log)
        if not args.no_console:
            print('Press Enter here, use Stop MatchTrader, or click Shut down API to turn it off.', flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        while not stop.exists() and all(child.poll() is None for child in children.values()):
            if not args.no_console and msvcrt.kbhit() and msvcrt.getwch() in {'\r', '\n'}:
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        log('Stopping the MatchTrader API; finishing active requests and retaining logs...')
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
        log('MatchTrader API is OFF. It will stay off until you start it.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop', action='store_true', help='Ask the running launcher to stop everything')
    parser.add_argument('--setup', action='store_true', help='Check .env first and prompt for missing credentials')
    parser.add_argument('--detach', action='store_true', help='Run the launcher hidden and return once the API answers')
    parser.add_argument('--auto-start', action='store_true', help='Connect the configured account and start capture')
    parser.add_argument('--no-console', action='store_true', help='No keyboard; stop only through the stop file')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--config', type=Path, default=ROOT / 'local-runtime.json')
    parser.add_argument('--runtime', type=Path, default=ROOT / 'data' / 'runtime')
    args = parser.parse_args(argv)
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    if args.stop:
        (runtime / 'stop.requested').touch()
        print('Stop requested. The launcher will finish active exchanges and close all three services.')
        return 0
    if args.setup:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        env_file = (args.config.resolve().parent / config['env']).resolve()
        ensure_env(env_file)
    if args.detach:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        return detach(args, f"http://127.0.0.1:{int(config.get('dashboard_port', 8765))}")
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
