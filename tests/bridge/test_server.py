import json

from matchtrader.bridge import ShadowBridge
from matchtrader.bridge.server import ingest, serve

TOKEN = "test-only-token-" * 3


def test_tokenless_ingress_and_invalid_inputs(tmp_path, event_payload):
    with ShadowBridge("123", tmp_path / "journal.db") as bridge:
        body = json.dumps(event_payload).encode()
        assert ingest("", body, "", bridge)[0] == 202
        assert ingest("Bearer " + TOKEN, b"x" * 16385, TOKEN, bridge)[0] == 413
        assert ingest("Bearer " + TOKEN, b"{}", TOKEN, bridge)[0] == 400
        assert ingest("Bearer " + TOKEN, b"[]", TOKEN, bridge)[0] == 400
        status, result = ingest("Bearer " + TOKEN, body, TOKEN, bridge)
        assert status == 202 and result["mode"] == "shadow"
        assert not result["ready_for_execution"]
        assert bridge.journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_server_binds_only_loopback(monkeypatch):
    class FakeServer:
        def __init__(self, address, handler):
            assert address == ("127.0.0.1", 8765)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def serve_forever(self, **kwargs):
            pass

    monkeypatch.setattr("matchtrader.bridge.server.HTTPServer", FakeServer)
    serve(None)
