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
import urllib.error
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
    # Optional keys are asked once, when the line is absent altogether; an empty answer is written
    # as an empty line so the question is not repeated on every start.
    for key, prompt, default, _secret in OPTIONAL:
        if key in values:
            continue
        suffix = f' [{default}]' if default else ''
        updates[key] = ask(f'  {prompt}{suffix}: ').strip() or default
    if not values.get('AQF_BRIDGE_TOKEN'):
        updates['AQF_BRIDGE_TOKEN'] = secrets.token_urlsafe(32)
        out('  Generated a local bridge token (AQF_BRIDGE_TOKEN) for the Quantower extension.')
    if updates:
        write_env(path, updates)
        out(f'  Saved {", ".join(updates)} to {path}.')
    values.update(updates)
    return values


# ---- host requirements ---------------------------------------------------------------------------
def probe_platform(url, timeout=8):
    """One HTTPS GET of the broker's platform details over TLS 1.3; returns the HTTP status."""
    import ssl
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url.rstrip('/') + '/manager/platform-details',
                                     headers={'User-Agent': 'hcamm-matchtrader/0.1.0', 'Accept': 'application/json'})
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def port_free(port):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def check_host(config_path, *, probe=probe_platform, min_free_mb=500):
    """What this machine needs before the launcher can run. Returns (status, name, detail) rows;
    status is OK, WARN (it will run, but something is off) or FAIL (it will not run)."""
    import platform
    import shutil
    rows = []

    def add(status, name, detail=''):
        rows.append((status, name, detail))

    add('OK' if sys.version_info >= (3, 12) else 'FAIL', 'Python 3.12 or later',
        f'{platform.python_version()} at {sys.executable}')
    add('OK' if platform.system() == 'Windows' else 'FAIL', 'Windows', platform.platform())
    config_path = Path(config_path)
    if not config_path.exists():
        add('FAIL', 'local-runtime.json', f'missing: {config_path}; copy local-runtime.json.example')
        return rows
    try:
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    except ValueError as error:
        add('FAIL', 'local-runtime.json', f'not valid JSON ({error})')
        return rows
    base = config_path.resolve().parent
    resolve = lambda key: (base / config[key]).resolve() if key in config else None  # noqa: E731
    python = resolve('python')
    add('OK' if python and python.is_file() else 'FAIL', 'Python environment (.venv)',
        str(python) if python else 'no "python" entry')
    dist = base / 'frontend' / 'dist' / 'index.html'
    add('OK' if dist.is_file() else 'FAIL', 'Dashboard build (frontend/dist)',
        str(dist) if dist.is_file() else 'run: npm.cmd --prefix frontend run build')
    relay = resolve('relay_config')
    add('OK' if relay and relay.is_file() else 'FAIL', 'Relay config', str(relay) if relay else 'no "relay_config" entry')
    env_file = resolve('env')
    values = read_env(env_file) if env_file and env_file.is_file() else {}
    missing = [key for key, *_ in REQUIRED if not values.get(key)]
    if not env_file or not env_file.is_file():
        add('WARN', 'Credentials (.env)', 'missing; setup will ask for them')
    elif missing:
        add('WARN', 'Credentials (.env)', 'setup will ask for: ' + ', '.join(missing))
    else:
        add('OK', 'Credentials (.env)', f'{env_file} has every required key')
    if values.get('AQF_ENABLE_WRITES', '').lower() != 'true':
        add('WARN', 'Broker writes', 'AQF_ENABLE_WRITES is not true: live sends are refused')
    else:
        add('OK', 'Broker writes', 'AQF_ENABLE_WRITES=true')
    for key, default in [('dashboard_port', 8765), ('ws_port', 8767), ('relay_port', 8787)]:
        port = int(config.get(key, default))
        if port == 0:
            continue
        add('OK' if port_free(port) else 'FAIL', f'Port {port} ({key})',
            'free' if port_free(port) else 'in use: an instance may already be running; use Stop MatchTrader')
    data = resolve('data') or base / 'data'
    try:
        data.mkdir(parents=True, exist_ok=True)
        marker = data / '.write-check'
        marker.write_text('ok')
        marker.unlink()
        add('OK', 'Data folder writable', str(data))
    except OSError as error:
        add('FAIL', 'Data folder writable', f'{data}: {type(error).__name__}')
    free_mb = shutil.disk_usage(base).free // (1024 * 1024)
    add('OK' if free_mb >= min_free_mb else 'WARN', 'Free disk space', f'{free_mb} MB free')
    ledger = values.get('AQF_R01_LEDGER')
    if ledger:
        add('OK' if Path(ledger).is_file() else 'WARN', 'R01 ledger',
            ledger if Path(ledger).is_file() else f'{ledger} not found; R01 observation and lane stay idle')
    else:
        add('WARN', 'R01 ledger', 'AQF_R01_LEDGER not set; R01 observation and lane stay idle')
    p01 = Path(values.get('AQF_P01_LOG_PATH') or 'C:/Quantower/Settings/Scripts/Indicators/_HCAMM_Shared/P01_RR.log')
    add('OK' if p01.is_file() else 'WARN', 'P01 log', str(p01) if p01.is_file() else f'{p01} not found; P01 copying stays idle')
    url = values.get('AQF_PLATFORM_URL')
    if url:
        try:
            status = probe(url)
            add('OK' if status < 500 else 'WARN', 'Broker reachable over TLS 1.3', f'{url} answered HTTP {status}')
        except Exception as error:
            add('WARN', 'Broker reachable over TLS 1.3', f'{url}: {type(error).__name__}; connect will fail until it is')
    return rows


def print_check(rows, out=print):
    width = max(len(name) for _, name, _ in rows)
    for status, name, detail in rows:
        out(f'  [{status:4s}] {name.ljust(width)}  {detail}')
    fails = [name for status, name, _ in rows if status == 'FAIL']
    warns = [name for status, name, _ in rows if status == 'WARN']
    out(f'  {len(rows) - len(fails) - len(warns)} ok, {len(warns)} warnings, {len(fails)} failures')
    return not fails


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
    parser.add_argument('--check', action='store_true', help='Report whether this machine meets the requirements')
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
    if args.check:
        print('Host requirements:')
        if not print_check(check_host(args.config)):
            print('Fix the failures above, then start again.')
            return 1
        if not (args.setup or args.detach or args.auto_start):
            return 0   # a bare --check reports and stops; it never starts anything
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
