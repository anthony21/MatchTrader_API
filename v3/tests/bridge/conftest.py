from datetime import UTC, datetime

import pytest


@pytest.fixture
def event_payload():
    return {
        "source_machine": "machine-test",
        "strategy_instance": "r01-test",
        "event_id": "event-1",
        "source_order_id": "order-1",
        "revision": 1,
        "emitted_at": datetime.now(UTC).isoformat(),
        "account_id": "123",
        "action": "CREATE",
        "instrument": "XAUUSD",
        "side": "SELL",
        "order_type": "LIMIT",
        "volume_lots": "0.02",
        "price": "2400",
        "sl_price": "2410",
        "tp_price": "2380",
    }
