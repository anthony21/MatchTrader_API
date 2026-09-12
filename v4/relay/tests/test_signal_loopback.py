"""Real loopback receipt with a fake MatchTrader destination; no external connections."""

import base64
import http.client
import json
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transparent_proxy import ProxyServer

from matchtrader.core.settings import Settings
from matchtrader.dashboard.controller import DashboardController
from matchtrader.dashboard.server import DashboardHTTPServer
from matchtrader.models.operation import Operation


def test_local_receipt_opens_one_fake_copy_with_configured_volume_and_no_tb_calls(tmp_path, monkeypatch):
    def external_forbidden(*args, **kwargs):
        raise AssertionError("TradingBox/external HTTPS must never be contacted")

    monkeypatch.setattr(http.client, "HTTPSConnection", external_forbidden)
    controller = DashboardController(
        Settings(platform_url="https://broker.example", account_id="demo"),
        tmp_path / "data",
        interactive_copying=True,
    )
    calls = []

    class Broker:
        connection = SimpleNamespace(session_expires_at=None, account_id='demo')

        def instruments(self):
            return [
                SimpleNamespace(
                    symbol="NAS100",
                    model_dump=lambda: {"volumeMin": "0.1", "volumeMax": "10", "volumeStep": "0.1"},
                )
            ]

        def create_pending_order(self, **kwargs):
            calls.append(kwargs)
            return Operation(status="OK", orderId="fake-order-one")

        def close(self):
            pass

    controller.api = Broker()
    controller.connection = "connected"
    controller.native.demo_verified = True
    controller.configure_signals(
        {
            "machine_id": "qt",
            "source": "chain",
            "destination_account": "demo",
            "exclusive_destination": True,
            "symbols": {
                "US TECH 100": {
                    "destination": "NAS100",
                    "fixed_lots": "0.2",
                    "order_type": "LIMIT",
                    "same_price_scale": True,
                }
            },
        }
    )
    controller.set_signal_copying(True)
    assets = tmp_path / "assets"
    assets.mkdir()
    token = "test-local-token-with-at-least-32-characters"
    server = DashboardHTTPServer(("127.0.0.1", 0), controller, assets, token)
    proxy = ProxyServer(
        ("127.0.0.1", 0),
        "https://tradingbox.pro",
        tmp_path / "logs",
        receiver_port=server.server_port,
        receiver_token=token,
    )
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in [server, proxy]]
    for thread in threads:
        thread.start()
    signal = {
        "clientEventId": "same-event",
        "label": "loopback-order-one",
        "machineId": "qt",
        "source": "chain",
        "kind": "intent",
        "timestampUtc": datetime.now(UTC).isoformat(),
        "symbol": "US TECH 100",
        "side": "short",
        "entry": 100,
        "stopLoss": 105,
        "takeProfit": 95,
        "volume": 0,
        "mode": "log",
    }
    try:
        for index in range(2):
            body = json.dumps([{**signal, **({"l2Class": ""} if index else {})}]).encode()
            client = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
            client.request("POST", "/api/hcamm/events", body=body)
            response = client.getresponse()
            result = json.loads(response.read())
            client.close()
            assert response.status == 202 and result["origin"] == "x.0.1"
            assert result["forwarded_to_tradingbox"] is False
            assert result["results"][0]["status"] == "accepted"
            assert result["results"][0]["duplicate"] == bool(index)
        assert len(calls) == 1 and str(calls[0]["volume"]) == "0.2"
        controller.set_signal_copying(False)
        batch = [{**signal, "clientEventId": f"batch-{i}", "label": "x" * 200,
                  "kind": "intent" if i % 2 else "closed"} for i in range(46)]
        body = json.dumps(batch).encode()
        assert len(body) > 16384
        client = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
        client.request("POST", "/api/hcamm/events", body=body)
        response = client.getresponse()
        result = json.loads(response.read())
        client.close()
        assert response.status == 202 and len(result["results"]) == 46
        assert len(calls) == 1
        client = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
        client.request("POST", "/api/hcamm/events", body=b"x" * (1024 * 1024 + 1))
        response = client.getresponse()
        response.read()
        client.close()
        assert response.status == 413
        assert len(calls) == 1
        raw = json.loads(next((tmp_path / "logs").glob("raw-request-*")).read_text().splitlines()[0])
        assert json.loads(base64.b64decode(raw["body_base64"]))[0]["volume"] == 0
    finally:
        for s in [proxy, server]:
            s.shutdown()
            s.server_close()
        for thread in threads:
            thread.join()
        controller.close()
