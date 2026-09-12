"""Run the x.0.1 relay. Forwarding follows the private config's `forward` flag.

With forward=true the relay is a transparent observer: the request reaches the
configured upstream with the same path, headers and body, and the upstream's own
status, headers and body are returned to the robot unchanged. Both directions are
logged. Nothing is added to or removed from the exchange.
"""
import argparse
import json
import threading
import time
from pathlib import Path

from dotenv import dotenv_values
from lifecycle import stopping
from transparent_proxy import ProxyServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('relay.json'))
    parser.add_argument('--port', type=int)
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--env', type=Path, required=True)
    parser.add_argument('--receiver-port', type=int, default=8765)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    forward = bool(config.get('forward', False))
    upstream = config.get('upstream', 'http://127.0.0.1')
    if forward and not upstream.startswith('https://'):
        parser.error('Forwarding requires an https upstream origin')
    token = dotenv_values(args.env).get('MTR_BRIDGE_TOKEN') or ''
    if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        parser.error('Configure the local receiver token')
    logs = Path(config.get('logDir', 'logs'))
    if not logs.is_absolute():
        logs = args.config.parent / logs
    host = config.get('listenHost', '127.0.0.1')
    if host not in {'127.0.0.1', 'localhost'}:
        parser.error('This release listens on local loopback only')
    with ProxyServer((host, args.port if args.port is not None else config.get('listenPort', 8787)),
                     upstream, logs, forward=forward, receiver_port=args.receiver_port, receiver_token=token) as server:
        mode = f'pass-through to {upstream}' if forward else 'TradingBox forwarding OFF'
        print(f'x.0.1 relay ({mode}) listening on {host}:{server.server_port}', flush=True)
        if args.stop_file:
            def watch_stop():
                while not stopping(args.stop_file):
                    time.sleep(0.25)
                server.shutdown()
            threading.Thread(target=watch_stop, daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
