"""Protect the verified SDK path without submitting another broker order."""

import json
from decimal import Decimal

import httpx


def test_pending_create_cancel_and_readback_contract(api_factory):
    """Preserve numeric bracket payloads, selected-account routing and exact-ID cleanup."""
    original_id, test_id = "existing-order", "new-test-order"
    pending = [
        {
            "id": original_id,
            "symbol": "XAUUSD",
            "side": "SELL",
            "type": "LIMIT",
            "volume": "0.01",
            "activationPrice": "4395.62",
        }
    ]
    mutations = []

    def broker(request):
        path = request.url.path
        if path.endswith("/manager/mtr-login"):
            return None
        assert path.startswith("/mtr-api/system-1/")
        assert request.headers["Auth-trading-api"] == "trading-test"
        assert "co-auth=session-test" in request.headers["Cookie"]
        assert request.headers["User-Agent"] == "hcamm-matchtrader/0.1.0"
        if path.endswith("/active-orders"):
            return httpx.Response(200, json={"orders": pending})
        if path.endswith("/open-positions"):
            return httpx.Response(200, json={"positions": []})
        body = json.loads(request.content)
        mutations.append((path.rsplit("/", 1)[-1], body))
        if path.endswith("/pending-order/create"):
            assert request.method == "POST"
            assert body == {
                "instrument": "XAUUSD",
                "orderSide": "BUY",
                "type": "LIMIT",
                "volume": 1,
                "price": 4340,
                "slPrice": 4330,
                "tpPrice": 4350,
                "isMobile": False,
            }
            pending.append(
                {
                    "id": test_id,
                    "symbol": "XAUUSD",
                    "side": "BUY",
                    "type": "LIMIT",
                    "volume": "1",
                    "activationPrice": "4340",
                    "stopLoss": "4330",
                    "takeProfit": "4350",
                }
            )
            return httpx.Response(200, json={"status": "OK", "orderId": test_id, "errorMessage": ""})
        assert path.endswith("/pending-order/cancel")
        assert body == {
            "instrument": "XAUUSD",
            "id": test_id,
            "orderSide": "BUY",
            "type": "LIMIT",
            "isMobile": False,
        }
        pending[:] = [r for r in pending if r["id"] != test_id]
        return httpx.Response(
            200, json={"status": "OK", "orderId": test_id, "errorCode": "UNKNOWN_ERROR", "errorMessage": ""}
        )

    api, _ = api_factory(broker)
    with api:
        api.login()
        assert api.connection.account_id == "123"
        assert [r.id for r in api.active_orders()] == [original_id]
        created = api.create_pending_order(
            instrument="XAUUSD",
            orderSide="BUY",
            type="LIMIT",
            volume=Decimal("1"),
            price=Decimal("4340"),
            slPrice=Decimal("4330"),
            tpPrice=Decimal("4350"),
        )
        assert created.status == "OK" and created.orderId == test_id
        cancelled = api.cancel_pending_order(
            instrument="XAUUSD",
            id=created.orderId,
            orderSide="BUY",
            type="LIMIT",
        )
        assert cancelled.status == "OK" and cancelled.orderId == test_id
        assert cancelled.model_dump()["errorCode"] == "UNKNOWN_ERROR"
        assert [r.id for r in api.active_orders()] == [original_id]
        assert api.open_positions() == []
    assert [action for action, _ in mutations] == ["create", "cancel"]
    assert api.closed
